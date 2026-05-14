"""
Views административной панели WMS.
Все views защищены декоратором @admin_required.
"""
from __future__ import annotations

from pathlib import Path

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.constants import ROLE_CHOICES, Roles
from core.export import ExportColumn, dispatch_export
from .decorators import admin_required
from .forms import BackupCreateForm, BackupUploadForm, SupplierForm, UserCreateForm, UserEditForm, WarehouseForm
from .models import AuditLog, BackupRecord
from .services import (
    create_database_backup,
    create_user_with_credentials,
    delete_backup,
    get_admin_dashboard_stats,
    log_action,
    reset_user_password,
    restore_database_backup,
    sync_backup_records,
    upload_backup_file,
)

User = get_user_model()


# ─────────────────────────────────────────────────────────────
#  Вспомогательные утилиты
# ─────────────────────────────────────────────────────────────

def _paginate(request: HttpRequest, qs, per_page: int = 25):
    from core.pagination import paginate_legacy
    return paginate_legacy(request, qs, per_page=per_page)


# ─────────────────────────────────────────────────────────────
#  Дашборд административной панели
# ─────────────────────────────────────────────────────────────

@admin_required
def dashboard(request: HttpRequest) -> HttpResponse:
    """Главный дашборд административной панели."""
    from django.urls import reverse as _reverse

    stats = get_admin_dashboard_stats()
    recent_audit = AuditLog.objects.select_related("user").order_by("-timestamp")[:10]

    quick_nav = [
        {"label": "Пользователи",     "url": _reverse("admin_panel:user_list")},
        {"label": "Журнал аудита",    "url": _reverse("admin_panel:audit_list")},
        {"label": "Резервные копии",  "url": _reverse("admin_panel:backup_list")},
        {"label": "Настройки",        "url": _reverse("admin_panel:settings")},
        {"label": "Справочники",      "url": _reverse("catalog_admin_home")},
        {"label": "Отчёты",           "url": _reverse("reports_home")},
    ]

    return render(request, "admin_panel/dashboard.html", {
        "stats": stats,
        "recent_audit": recent_audit,
        "quick_nav": quick_nav,
    })


# ─────────────────────────────────────────────────────────────
#  Управление пользователями
# ─────────────────────────────────────────────────────────────

@admin_required
def user_list(request: HttpRequest) -> HttpResponse:
    """Список пользователей с поиском, фильтрацией и сортировкой."""
    from core.sorting import apply_ordering

    q = (request.GET.get("q") or "").strip()
    role = request.GET.get("role", "")
    status = request.GET.get("status", "")

    qs = User.objects.all()

    if q:
        qs = qs.filter(
            Q(username__icontains=q)
            | Q(email__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
        )
    if role:
        qs = qs.filter(role=role)
    if status == "active":
        qs = qs.filter(is_active=True)
    elif status == "inactive":
        qs = qs.filter(is_active=False)

    qs, sort, order = apply_ordering(qs, request, {
        "username": "username",
        "name":     "first_name",
        "email":    "email",
        "role":     "role",
        "joined":   "date_joined",
        "active":   "is_active",
    }, default="username", default_order="asc")

    page_obj = _paginate(request, qs)

    return render(request, "admin_panel/users/list.html", {
        "page_obj": page_obj,
        "users": page_obj.object_list,
        "q": q,
        "role": role,
        "status": status,
        "role_choices": ROLE_CHOICES,
        "sort": sort,
        "order": order,
    })


@admin_required
def user_create(request: HttpRequest) -> HttpResponse:
    """Создание нового пользователя с автогенерацией пароля."""
    if request.method == "POST":
        form = UserCreateForm(request.POST)
        if form.is_valid():
            try:
                user, raw_password = create_user_with_credentials(
                    admin_user=request.user,
                    cleaned_data=form.cleaned_data,
                    request=request,
                )
                messages.success(
                    request,
                    f"Пользователь «{user.username}» создан. "
                    f"Пароль отправлен на {user.email}.",
                )
                # Показываем временный пароль однократно
                request.session["new_user_password"] = {
                    "username": user.username,
                    "password": raw_password,
                    "email": user.email,
                }
                return redirect("admin_panel:user_detail", pk=user.pk)
            except Exception as exc:
                messages.error(request, f"Ошибка создания пользователя: {exc}")
    else:
        form = UserCreateForm()

    return render(request, "admin_panel/users/form.html", {
        "form": form,
        "title": "Создать пользователя",
        "is_create": True,
    })


@admin_required
def user_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Просмотр пользователя. Показывает временный пароль однократно."""
    user_obj = get_object_or_404(User, pk=pk)
    new_credentials = request.session.pop("new_user_password", None)

    recent_actions = AuditLog.objects.filter(
        user=user_obj
    ).order_by("-timestamp")[:20]

    return render(request, "admin_panel/users/detail.html", {
        "user_obj": user_obj,
        "new_credentials": new_credentials,
        "recent_actions": recent_actions,
    })


@admin_required
def user_edit(request: HttpRequest, pk: int) -> HttpResponse:
    """Редактирование существующего пользователя."""
    user_obj = get_object_or_404(User, pk=pk)

    # Нельзя редактировать самого себя через эту форму (только через профиль)
    if user_obj == request.user:
        messages.warning(request, "Для изменения собственного профиля используйте страницу «Мой профиль».")
        return redirect("admin_panel:user_detail", pk=pk)

    if request.method == "POST":
        # Снимаем «старые» значения ДО валидации формы:
        # ModelForm._post_clean() обновляет instance при is_valid(),
        # поэтому захватываем оригинальные значения заранее.
        old_role = user_obj.role
        old_active = user_obj.is_active
        form = UserEditForm(request.POST, instance=user_obj)
        if form.is_valid():
            form.save()

            changes: dict = {}
            if old_role != user_obj.role:
                changes["role"] = {"from": old_role, "to": user_obj.role}
            if old_active != user_obj.is_active:
                changes["is_active"] = {"from": old_active, "to": user_obj.is_active}

            log_action(
                actor=request.user,
                action=AuditLog.ActionType.UPDATE,
                resource_type="User",
                resource_id=str(user_obj.pk),
                resource_str=user_obj.username,
                changes=changes or None,
                request=request,
            )
            messages.success(request, f"Пользователь «{user_obj.username}» обновлён.")
            return redirect("admin_panel:user_detail", pk=pk)
    else:
        form = UserEditForm(instance=user_obj)

    return render(request, "admin_panel/users/form.html", {
        "form": form,
        "user_obj": user_obj,
        "title": f"Редактировать: {user_obj.username}",
        "is_create": False,
    })


@admin_required
def user_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """Удаление пользователя с подтверждением."""
    user_obj = get_object_or_404(User, pk=pk)

    if user_obj == request.user:
        messages.error(request, "Нельзя удалить собственную учётную запись.")
        return redirect("admin_panel:user_detail", pk=pk)

    if request.method == "POST":
        username = user_obj.username
        log_action(
            actor=request.user,
            action=AuditLog.ActionType.DELETE,
            resource_type="User",
            resource_id=str(user_obj.pk),
            resource_str=username,
            request=request,
        )
        user_obj.delete()
        messages.success(request, f"Пользователь «{username}» удалён.")
        return redirect("admin_panel:user_list")

    return render(request, "admin_panel/users/confirm_delete.html", {
        "user_obj": user_obj,
    })


@admin_required
@require_POST
def user_toggle_active(request: HttpRequest, pk: int) -> HttpResponse:
    """Блокировка / разблокировка пользователя (POST). Принимает reason."""
    user_obj = get_object_or_404(User, pk=pk)

    if user_obj == request.user:
        messages.error(request, "Нельзя заблокировать собственную учётную запись.")
        return redirect("admin_panel:user_detail", pk=pk)

    reason = (request.POST.get("reason") or "").strip()[:500]
    _apply_user_toggle(request.user, user_obj, reason=reason, request=request)

    status_word = "активирован" if user_obj.is_active else "заблокирован"
    messages.success(request, f"Пользователь «{user_obj.username}» {status_word}.")
    return redirect("admin_panel:user_detail", pk=pk)


def _apply_user_toggle(actor, target_user, *, reason: str = "", request=None) -> None:
    """
    Переключает is_active на target_user, пишет AuditLog (с причиной)
    и шлёт persistent in-app Notification — оно сохраняется в БД и
    остаётся после перезапуска сервера.
    """
    target_user.is_active = not target_user.is_active
    target_user.save(update_fields=["is_active"])

    action_type = (
        AuditLog.ActionType.ACTIVATE
        if target_user.is_active
        else AuditLog.ActionType.DEACTIVATE
    )
    changes = {"is_active": target_user.is_active}
    if reason:
        changes["reason"] = reason

    log_action(
        actor=actor,
        action=action_type,
        resource_type="User",
        resource_id=str(target_user.pk),
        resource_str=target_user.username,
        changes=changes,
        request=request,
    )

    # Persistent notification — хранится в БД (notifications.Notification),
    # переживает перезапуск, не зависит от Django messages framework.
    try:
        from notifications.services import notify
        from notifications.models import NotificationKind, NotificationPriority

        if target_user.is_active:
            title = "Доступ восстановлен"
            body = f"Администратор {actor.username} разблокировал вашу учётную запись."
            kind = NotificationKind.SUCCESS
            prio = NotificationPriority.NORMAL
        else:
            title = "Учётная запись заблокирована"
            body = f"Администратор {actor.username} заблокировал ваш доступ."
            if reason:
                body += f" Причина: {reason}"
            kind = NotificationKind.DANGER
            prio = NotificationPriority.HIGH

        notify(
            target_user,
            title=title, body=body,
            kind=kind, priority=prio,
            dedup_key=f"user-toggle-{target_user.pk}-{int(target_user.is_active)}",
        )
    except Exception:
        # уведомление не должно ломать основной поток
        pass


def _apply_user_role_change(actor, target_user, new_role: str, *, request=None) -> bool:
    """Меняет роль и пишет аудит + persistent notification."""
    if new_role == target_user.role:
        return False
    old_role = target_user.role
    target_user.role = new_role
    target_user.save(update_fields=["role"])

    log_action(
        actor=actor,
        action=AuditLog.ActionType.UPDATE,
        resource_type="User",
        resource_id=str(target_user.pk),
        resource_str=target_user.username,
        changes={"role": {"from": old_role, "to": new_role}},
        request=request,
    )
    try:
        from notifications.services import notify
        from notifications.models import NotificationKind
        notify(
            target_user,
            title="Роль изменена",
            body=f"Администратор {actor.username} изменил вашу роль: "
                 f"{old_role} → {new_role}.",
            kind=NotificationKind.INFO,
            dedup_key=f"user-role-{target_user.pk}-{new_role}",
        )
    except Exception:
        pass
    return True


@admin_required
@require_POST
def user_bulk_action(request: HttpRequest) -> HttpResponse:
    """
    Массовые операции над пользователями.

    POST поля:
        action      — "block" | "unblock" | "set_role"
        ids         — список User.pk через запятую
        reason      — причина блокировки/разблокировки (опционально)
        role        — код роли для action=set_role
    """
    raw_ids = (request.POST.get("ids") or "").strip()
    pks = [int(x) for x in raw_ids.split(",") if x.strip().isdigit()]
    action = (request.POST.get("action") or "").strip()
    reason = (request.POST.get("reason") or "").strip()[:500]
    new_role = (request.POST.get("role") or "").strip()

    if not pks:
        messages.error(request, "Не выбрано ни одного пользователя.")
        return redirect("admin_panel:user_list")
    if action not in {"block", "unblock", "set_role"}:
        messages.error(request, "Неизвестное действие.")
        return redirect("admin_panel:user_list")

    # Не позволяем себя самого
    pks = [pk for pk in pks if pk != request.user.pk]
    qs = User.objects.filter(pk__in=pks)

    affected = 0
    if action == "block":
        for u in qs:
            if u.is_active:
                _apply_user_toggle(request.user, u, reason=reason, request=request)
                affected += 1
        messages.success(request, f"Заблокировано пользователей: {affected}.")
    elif action == "unblock":
        for u in qs:
            if not u.is_active:
                _apply_user_toggle(request.user, u, reason=reason, request=request)
                affected += 1
        messages.success(request, f"Разблокировано пользователей: {affected}.")
    elif action == "set_role":
        valid_roles = {code for code, _ in ROLE_CHOICES}
        if new_role not in valid_roles:
            messages.error(request, "Некорректная роль.")
            return redirect("admin_panel:user_list")
        for u in qs:
            if _apply_user_role_change(request.user, u, new_role, request=request):
                affected += 1
        messages.success(
            request,
            f"Роль изменена у {affected} пользователей на «{dict(ROLE_CHOICES).get(new_role, new_role)}».",
        )

    return redirect("admin_panel:user_list")


@admin_required
@require_POST
def user_reset_password(request: HttpRequest, pk: int) -> HttpResponse:
    """Сброс пароля пользователя (POST). Новый пароль отправляется на email."""
    user_obj = get_object_or_404(User, pk=pk)

    try:
        raw_password = reset_user_password(
            admin_user=request.user,
            target_user=user_obj,
            request=request,
        )
        request.session["new_user_password"] = {
            "username": user_obj.username,
            "password": raw_password,
            "email": user_obj.email,
        }
        messages.success(
            request,
            f"Новый пароль для «{user_obj.username}» сгенерирован и отправлен на {user_obj.email}.",
        )
    except Exception as exc:
        messages.error(request, f"Ошибка сброса пароля: {exc}")

    return redirect("admin_panel:user_detail", pk=pk)


# ─────────────────────────────────────────────────────────────
#  Журнал аудита
# ─────────────────────────────────────────────────────────────

@admin_required
def audit_log_list(request: HttpRequest) -> HttpResponse:
    """Журнал действий администраторов."""
    from core.sorting import apply_ordering

    q = (request.GET.get("q") or "").strip()
    action_filter = request.GET.get("action", "")
    user_filter = request.GET.get("user_id", "")

    qs = AuditLog.objects.select_related("user")

    if q:
        qs = qs.filter(
            Q(resource_str__icontains=q)
            | Q(user__username__icontains=q)
            | Q(ip_address__icontains=q)
        )
    if action_filter:
        qs = qs.filter(action=action_filter)
    if user_filter:
        qs = qs.filter(user_id=user_filter)

    qs, sort, order = apply_ordering(qs, request, {
        "time":     "timestamp",
        "user":     "user__username",
        "action":   "action",
        "resource": "resource_str",
        "ip":       "ip_address",
    }, default="time", default_order="desc")

    page_obj = _paginate(request, qs, per_page=50)

    return render(request, "admin_panel/audit/list.html", {
        "page_obj": page_obj,
        "logs": page_obj.object_list,
        "q": q,
        "sort": sort,
        "order": order,
        "action_filter": action_filter,
        "user_filter": user_filter,
        "action_choices": AuditLog.ActionType.choices,
        "admin_users": User.objects.filter(
            Q(role=Roles.ADMIN) | Q(is_superuser=True)
        ).order_by("username"),
    })


# ─────────────────────────────────────────────────────────────
#  Резервные копии
# ─────────────────────────────────────────────────────────────

@admin_required
def backup_list(request: HttpRequest) -> HttpResponse:
    """Список резервных копий базы данных."""
    sync_backup_records()
    backups = BackupRecord.objects.all().order_by("-created_at")
    form = BackupCreateForm()
    upload_form = BackupUploadForm()
    return render(request, "admin_panel/backups/list.html", {
        "backups": backups,
        "form": form,
        "upload_form": upload_form,
    })


@admin_required
@require_POST
def backup_create(request: HttpRequest) -> HttpResponse:
    """Создание резервной копии (POST)."""
    form = BackupCreateForm(request.POST)
    if form.is_valid():
        try:
            record = create_database_backup(
                created_by=request.user,
                notes=form.cleaned_data.get("notes", ""),
            )
            messages.success(
                request,
                f"Резервная копия «{record.filename}» создана ({record.size_human}).",
            )
        except Exception as exc:
            messages.error(request, f"Ошибка создания резервной копии: {exc}")
    else:
        messages.error(request, "Форма заполнена некорректно.")
    return redirect("admin_panel:backup_list")


@admin_required
@require_POST
def backup_upload(request: HttpRequest) -> HttpResponse:
    """Загрузка готового файла резервной копии пользователем."""
    form = BackupUploadForm(request.POST, request.FILES)
    if form.is_valid():
        try:
            record = upload_backup_file(
                form.cleaned_data["backup_file"],
                actor=request.user,
                notes=form.cleaned_data.get("notes", ""),
            )
            messages.success(
                request,
                f"Файл резервной копии «{record.filename}» загружен. "
                "Теперь его можно скачать или восстановить.",
            )
        except Exception as exc:
            messages.error(request, f"Ошибка загрузки резервной копии: {exc}")
    else:
        errors = "; ".join(
            f"{field}: {', '.join(messages_for_field)}"
            for field, messages_for_field in form.errors.items()
        )
        messages.error(request, f"Форма загрузки заполнена некорректно. {errors}")
    return redirect("admin_panel:backup_list")


@admin_required
def backup_download(request: HttpRequest, filename: str) -> HttpResponse:
    """Скачивание файла резервной копии."""
    try:
        from .services import _safe_backup_path
        path = _safe_backup_path(filename)
    except ValueError:
        raise Http404("Файл не найден.")

    if not path.exists():
        raise Http404("Файл резервной копии не найден.")

    log_action(
        actor=request.user,
        action=AuditLog.ActionType.VIEW,
        resource_type="BackupRecord",
        resource_str=filename,
        request=request,
    )

    response = FileResponse(
        open(path, "rb"),
        as_attachment=True,
        filename=filename,
    )
    response["Content-Type"] = "application/octet-stream"
    return response


@admin_required
@require_POST
def backup_delete_view(request: HttpRequest, filename: str) -> HttpResponse:
    """Удаление резервной копии (POST)."""
    try:
        delete_backup(filename=filename, actor=request.user)
        messages.success(request, f"Резервная копия «{filename}» удалена.")
    except Exception as exc:
        messages.error(request, f"Ошибка удаления: {exc}")
    return redirect("admin_panel:backup_list")


@admin_required
@require_POST
def backup_restore(request: HttpRequest, filename: str) -> HttpResponse:
    """Восстановление базы данных из резервной копии (POST). Необратимо!"""
    confirm = request.POST.get("confirm_restore") == "yes"
    if not confirm:
        messages.warning(request, "Восстановление не подтверждено.")
        return redirect("admin_panel:backup_list")

    wipe_first = request.POST.get("wipe_first") == "yes"
    try:
        restore_database_backup(
            filename=filename, actor=request.user, wipe_first=wipe_first,
        )
        messages.success(
            request,
            f"База данных успешно восстановлена из «{filename}». "
            "Может потребоваться перезапуск сервера.",
        )
    except Exception as exc:
        messages.error(request, f"Ошибка восстановления: {exc}")
    return redirect("admin_panel:backup_list")


# ─────────────────────────────────────────────────────────────
#  Настройки системы
# ─────────────────────────────────────────────────────────────

@admin_required
def system_settings(request: HttpRequest) -> HttpResponse:
    """Просмотр системной информации и настроек."""
    from django.conf import settings as django_settings
    import django

    db = django_settings.DATABASES.get("default", {})
    db_info = {
        "ENGINE": db.get("ENGINE", "—"),
        "NAME": db.get("NAME", "—"),
        "HOST": db.get("HOST", "localhost"),
        "PORT": db.get("PORT", "5432"),
        "USER": db.get("USER", "—"),
    }

    installed_apps = [a for a in django_settings.INSTALLED_APPS if not a.startswith("django.")]

    return render(request, "admin_panel/settings/index.html", {
        "django_version": django.__version__,
        "debug": django_settings.DEBUG,
        "language": django_settings.LANGUAGE_CODE,
        "timezone": django_settings.TIME_ZONE,
        "db_info": db_info,
        "installed_apps": installed_apps,
        "media_root": str(getattr(django_settings, "MEDIA_ROOT", "—")),
        "static_root": str(getattr(django_settings, "STATIC_ROOT", "—")),
        "email_backend": django_settings.EMAIL_BACKEND,
        "backup_dir": str(getattr(django_settings, "BACKUP_DIR", Path(django_settings.BASE_DIR) / "backups")),
    })


# ═════════════════════════════════════════════════════════════
#  WMS-сущности — управление через административную панель
# ═════════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────────
#  Склады
# ─────────────────────────────────────────────────────────────

@admin_required
def wms_warehouse_list(request: HttpRequest) -> HttpResponse:
    """Список складов с поиском, фильтрацией и сортировкой."""
    from core.sorting import apply_ordering
    from catalog.models import Branch, Warehouse

    q = (request.GET.get("q") or "").strip()
    branch_filter = request.GET.get("branch", "")
    status_filter = request.GET.get("status", "")

    qs = Warehouse.objects.select_related("branch")
    if q:
        qs = qs.filter(Q(code__icontains=q) | Q(name__icontains=q) | Q(branch__name__icontains=q))
    if branch_filter:
        qs = qs.filter(branch_id=branch_filter)
    if status_filter == "active":
        qs = qs.filter(is_active=True)
    elif status_filter == "inactive":
        qs = qs.filter(is_active=False)

    qs, sort, order = apply_ordering(qs, request, {
        "code":   "code",
        "name":   "name",
        "branch": "branch__name",
        "active": "is_active",
    }, default="code", default_order="asc")

    page_obj = _paginate(request, qs, per_page=25)
    branches = Branch.objects.filter(is_active=True).order_by("code")

    return render(request, "admin_panel/wms/warehouses/list.html", {
        "page_obj": page_obj,
        "q": q,
        "sort": sort,
        "order": order,
        "branch_filter": branch_filter,
        "status_filter": status_filter,
        "branches": branches,
        "total": qs.count(),
    })


@admin_required
def wms_warehouse_create(request: HttpRequest) -> HttpResponse:
    """Создание нового склада."""
    if request.method == "POST":
        form = WarehouseForm(request.POST)
        if form.is_valid():
            warehouse = form.save()
            log_action(
                actor=request.user,
                action=AuditLog.ActionType.CREATE,
                resource_type="Warehouse",
                resource_id=str(warehouse.pk),
                resource_str=str(warehouse),
                request=request,
            )
            messages.success(request, f"Склад «{warehouse}» создан.")
            return redirect("admin_panel:wms_warehouse_list")
    else:
        form = WarehouseForm()
    return render(request, "admin_panel/wms/warehouses/form.html", {
        "form": form,
        "title": "Создать склад",
        "is_create": True,
    })


@admin_required
def wms_warehouse_edit(request: HttpRequest, pk: int) -> HttpResponse:
    """Редактирование склада."""
    from catalog.models import Warehouse
    warehouse = get_object_or_404(Warehouse, pk=pk)
    if request.method == "POST":
        form = WarehouseForm(request.POST, instance=warehouse)
        if form.is_valid():
            form.save()
            log_action(
                actor=request.user,
                action=AuditLog.ActionType.UPDATE,
                resource_type="Warehouse",
                resource_id=str(warehouse.pk),
                resource_str=str(warehouse),
                request=request,
            )
            messages.success(request, f"Склад «{warehouse}» обновлён.")
            return redirect("admin_panel:wms_warehouse_list")
    else:
        form = WarehouseForm(instance=warehouse)
    return render(request, "admin_panel/wms/warehouses/form.html", {
        "form": form,
        "title": f"Редактировать склад — {warehouse}",
        "warehouse": warehouse,
        "is_create": False,
    })


@admin_required
def wms_warehouse_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """Удаление склада (с подтверждением)."""
    from catalog.models import Warehouse
    warehouse = get_object_or_404(Warehouse, pk=pk)
    if request.method == "POST":
        name = str(warehouse)
        try:
            warehouse.delete()
            log_action(
                actor=request.user,
                action=AuditLog.ActionType.DELETE,
                resource_type="Warehouse",
                resource_id=str(pk),
                resource_str=name,
                request=request,
            )
            messages.success(request, f"Склад «{name}» удалён.")
        except Exception as exc:
            messages.error(request, f"Невозможно удалить склад: {exc}")
        return redirect("admin_panel:wms_warehouse_list")
    return render(request, "admin_panel/wms/warehouses/confirm_delete.html", {
        "warehouse": warehouse,
    })


# ─────────────────────────────────────────────────────────────
#  Поставщики
# ─────────────────────────────────────────────────────────────

@admin_required
def wms_supplier_list(request: HttpRequest) -> HttpResponse:
    """Список поставщиков."""
    from core.sorting import apply_ordering
    from receiving.models import Supplier

    q = (request.GET.get("q") or "").strip()
    status_filter = request.GET.get("status", "")

    qs = Supplier.objects.all()
    if q:
        qs = qs.filter(Q(code__icontains=q) | Q(name__icontains=q))
    if status_filter == "active":
        qs = qs.filter(is_active=True)
    elif status_filter == "inactive":
        qs = qs.filter(is_active=False)

    qs, sort, order = apply_ordering(qs, request, {
        "code":   "code",
        "name":   "name",
        "active": "is_active",
    }, default="name", default_order="asc")

    page_obj = _paginate(request, qs, per_page=25)
    return render(request, "admin_panel/wms/suppliers/list.html", {
        "page_obj": page_obj,
        "q": q,
        "sort": sort,
        "order": order,
        "status_filter": status_filter,
        "total": qs.count(),
    })


@admin_required
def wms_supplier_create(request: HttpRequest) -> HttpResponse:
    """Создание поставщика."""
    if request.method == "POST":
        form = SupplierForm(request.POST)
        if form.is_valid():
            supplier = form.save()
            log_action(
                actor=request.user,
                action=AuditLog.ActionType.CREATE,
                resource_type="Supplier",
                resource_id=str(supplier.pk),
                resource_str=str(supplier),
                request=request,
            )
            messages.success(request, f"Поставщик «{supplier.name}» создан.")
            return redirect("admin_panel:wms_supplier_list")
    else:
        form = SupplierForm()
    return render(request, "admin_panel/wms/suppliers/form.html", {
        "form": form, "title": "Создать поставщика", "is_create": True,
    })


@admin_required
def wms_supplier_edit(request: HttpRequest, pk: int) -> HttpResponse:
    """Редактирование поставщика."""
    from receiving.models import Supplier
    supplier = get_object_or_404(Supplier, pk=pk)
    if request.method == "POST":
        form = SupplierForm(request.POST, instance=supplier)
        if form.is_valid():
            form.save()
            log_action(
                actor=request.user,
                action=AuditLog.ActionType.UPDATE,
                resource_type="Supplier",
                resource_id=str(supplier.pk),
                resource_str=str(supplier),
                request=request,
            )
            messages.success(request, f"Поставщик «{supplier.name}» обновлён.")
            return redirect("admin_panel:wms_supplier_list")
    else:
        form = SupplierForm(instance=supplier)
    return render(request, "admin_panel/wms/suppliers/form.html", {
        "form": form,
        "title": f"Редактировать поставщика — {supplier.name}",
        "supplier": supplier,
        "is_create": False,
    })


@admin_required
@require_POST
def wms_supplier_toggle_active(request: HttpRequest, pk: int) -> HttpResponse:
    """Активация / деактивация поставщика."""
    from receiving.models import Supplier
    supplier = get_object_or_404(Supplier, pk=pk)
    supplier.is_active = not supplier.is_active
    supplier.save(update_fields=["is_active"])
    action = AuditLog.ActionType.ACTIVATE if supplier.is_active else AuditLog.ActionType.DEACTIVATE
    log_action(actor=request.user, action=action, resource_type="Supplier",
               resource_id=str(pk), resource_str=supplier.name, request=request)
    verb = "активирован" if supplier.is_active else "деактивирован"
    messages.success(request, f"Поставщик «{supplier.name}» {verb}.")
    return redirect("admin_panel:wms_supplier_list")


@admin_required
def wms_supplier_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """Удаление поставщика."""
    from receiving.models import Supplier
    supplier = get_object_or_404(Supplier, pk=pk)
    if request.method == "POST":
        name = supplier.name
        try:
            supplier.delete()
            log_action(
                actor=request.user,
                action=AuditLog.ActionType.DELETE,
                resource_type="Supplier",
                resource_id=str(pk),
                resource_str=name,
                request=request,
            )
            messages.success(request, f"Поставщик «{name}» удалён.")
        except Exception as exc:
            messages.error(request, f"Невозможно удалить поставщика: {exc}")
        return redirect("admin_panel:wms_supplier_list")
    return render(request, "admin_panel/wms/suppliers/confirm_delete.html", {
        "supplier": supplier,
    })


# ─────────────────────────────────────────────────────────────
#  Товары (только просмотр — CRUD через catalog_admin)
# ─────────────────────────────────────────────────────────────

@admin_required
def wms_product_list(request: HttpRequest) -> HttpResponse:
    """Обзорный список товаров с поиском и фильтрацией."""
    from catalog.models import Brand, Category, Product

    q = (request.GET.get("q") or "").strip()
    brand_filter = request.GET.get("brand", "")
    category_filter = request.GET.get("category", "")

    from core.sorting import apply_ordering

    qs = Product.objects.select_related("brand", "category")
    if q:
        qs = qs.filter(
            Q(internal_sku__icontains=q)
            | Q(name__icontains=q)
            | Q(oem_number__icontains=q)
            | Q(barcode__icontains=q)
        )
    if brand_filter:
        qs = qs.filter(brand_id=brand_filter)
    if category_filter:
        qs = qs.filter(category_id=category_filter)

    qs, sort, order = apply_ordering(qs, request, {
        "sku":      "internal_sku",
        "name":     "name",
        "brand":    "brand__name",
        "category": "category__name",
        "oem":      "oem_number",
        "barcode":  "barcode",
    }, default="sku", default_order="asc")

    export_resp = dispatch_export(
        request, qs, _PRODUCT_EXPORT_COLUMNS,
        filename="products", title="Каталог товаров",
    )
    if export_resp is not None:
        return export_resp

    page_obj = _paginate(request, qs, per_page=30)
    brands = Brand.objects.order_by("name")
    categories = Category.objects.order_by("name")
    return render(request, "admin_panel/wms/products/list.html", {
        "page_obj": page_obj,
        "q": q,
        "brand_filter": brand_filter,
        "category_filter": category_filter,
        "brands": brands,
        "categories": categories,
        "total": qs.count(),
        "sort": sort,
        "order": order,
    })


@admin_required
@require_POST
def wms_product_bulk_action(request: HttpRequest) -> HttpResponse:
    """
    Массовые операции над выбранными товарами.

    Поля POST:
        action     — bulk-действие: "delete" | "set_category" | "set_brand"
        ids        — список Product.pk через запятую
        category   — pk Category (для action=set_category)
        brand      — pk Brand    (для action=set_brand)
    """
    from catalog.models import Brand, Category, Product

    raw_ids = (request.POST.get("ids") or "").strip()
    pks = [int(x) for x in raw_ids.split(",") if x.strip().isdigit()]
    action = (request.POST.get("action") or "").strip()

    if not pks:
        messages.error(request, "Не выбрано ни одного товара.")
        return redirect("admin_panel:wms_product_list")
    if action not in {"delete", "set_category", "set_brand"}:
        messages.error(request, "Неизвестное действие.")
        return redirect("admin_panel:wms_product_list")

    qs = Product.objects.filter(pk__in=pks)
    count = qs.count()

    if action == "delete":
        try:
            qs.delete()
            log_action(
                actor=request.user,
                action=AuditLog.ActionType.DELETE,
                resource_type="Product",
                resource_str=f"bulk delete {count} items",
                changes={"count": count, "ids": pks},
                request=request,
            )
            messages.success(request, f"Удалено товаров: {count}.")
        except Exception as exc:
            messages.error(request, f"Ошибка удаления: {exc}")

    elif action == "set_category":
        cat_id = (request.POST.get("category") or "").strip()
        if not cat_id.isdigit() or not Category.objects.filter(pk=int(cat_id)).exists():
            messages.error(request, "Некорректная категория.")
            return redirect("admin_panel:wms_product_list")
        category = Category.objects.get(pk=int(cat_id))
        qs.update(category=category)
        log_action(
            actor=request.user,
            action=AuditLog.ActionType.UPDATE,
            resource_type="Product",
            resource_str=f"bulk set_category={category.name} for {count} items",
            changes={"category_id": category.pk, "ids": pks},
            request=request,
        )
        messages.success(request, f"Изменена категория у {count} товаров на «{category.name}».")

    elif action == "set_brand":
        brand_id = (request.POST.get("brand") or "").strip()
        if not brand_id.isdigit() or not Brand.objects.filter(pk=int(brand_id)).exists():
            messages.error(request, "Некорректный бренд.")
            return redirect("admin_panel:wms_product_list")
        brand = Brand.objects.get(pk=int(brand_id))
        qs.update(brand=brand)
        log_action(
            actor=request.user,
            action=AuditLog.ActionType.UPDATE,
            resource_type="Product",
            resource_str=f"bulk set_brand={brand.name} for {count} items",
            changes={"brand_id": brand.pk, "ids": pks},
            request=request,
        )
        messages.success(request, f"Изменён бренд у {count} товаров на «{brand.name}».")

    return redirect("admin_panel:wms_product_list")


# ─────────────────────────────────────────────────────────────
#  Заказы (обзор)
# ─────────────────────────────────────────────────────────────

@admin_required
def wms_order_list(request: HttpRequest) -> HttpResponse:
    """Обзорный список заказов с фильтрацией и сортировкой."""
    from core.sorting import apply_ordering
    from picking.models import Order, OrderStatus

    q = (request.GET.get("q") or "").strip()
    status_filter = request.GET.get("status", "")

    qs = Order.objects.select_related("created_by")
    if q:
        qs = qs.filter(Q(number__icontains=q) | Q(customer_name__icontains=q))
    if status_filter:
        qs = qs.filter(status=status_filter)

    qs, sort, order = apply_ordering(qs, request, {
        "number":   "number",
        "customer": "customer_name",
        "status":   "status",
        "source":   "source",
        "created":  "created_at",
        "creator":  "created_by__username",
    }, default="created", default_order="desc")

    export_resp = dispatch_export(
        request, qs, _ORDER_EXPORT_COLUMNS,
        filename="orders", title="Заказы",
    )
    if export_resp is not None:
        return export_resp

    page_obj = _paginate(request, qs, per_page=25)
    return render(request, "admin_panel/wms/orders/list.html", {
        "page_obj": page_obj,
        "q": q,
        "sort": sort,
        "order": order,
        "status_filter": status_filter,
        "status_choices": OrderStatus.choices,
        "total": qs.count(),
    })


# ─────────────────────────────────────────────────────────────
#  Остатки (обзор)
# ─────────────────────────────────────────────────────────────

@admin_required
def wms_stock_list(request: HttpRequest) -> HttpResponse:
    """Обзор остатков с поиском и сортировкой."""
    from core.sorting import apply_ordering
    from inventory.models import Stock

    q = (request.GET.get("q") or "").strip()
    qs = Stock.objects.select_related(
        "product", "storage_location", "storage_location__zone",
        "storage_location__zone__warehouse",
    )

    if q:
        qs = qs.filter(
            Q(product__internal_sku__icontains=q)
            | Q(product__name__icontains=q)
            | Q(storage_location__code__icontains=q)
        )

    qs, sort, order = apply_ordering(qs, request, {
        "sku":      "product__internal_sku",
        "name":     "product__name",
        "location": "storage_location__code",
        "qty":      "qty_available",
        "reserved": "qty_reserved",
        "batch":    "batch_no",
    }, default="sku", default_order="asc")

    page_obj = _paginate(request, qs, per_page=30)
    return render(request, "admin_panel/wms/stock/list.html", {
        "page_obj": page_obj,
        "q": q,
        "sort": sort,
        "order": order,
        "total": qs.count(),
    })


# ─────────────────────────────────────────────────────────────
#  Приёмки (обзор)
# ─────────────────────────────────────────────────────────────

@admin_required
def wms_receiving_list(request: HttpRequest) -> HttpResponse:
    """Обзор документов приёмки."""
    from core.sorting import apply_ordering
    from receiving.models import Receiving, ReceivingStatus

    q = (request.GET.get("q") or "").strip()
    status_filter = request.GET.get("status", "")

    qs = Receiving.objects.select_related("created_by", "warehouse")
    if q:
        qs = qs.filter(Q(number__icontains=q) | Q(supplier_name__icontains=q))
    if status_filter:
        qs = qs.filter(status=status_filter)

    qs, sort, order = apply_ordering(qs, request, {
        "number":   "number",
        "supplier": "supplier_name",
        "status":   "status",
        "warehouse": "warehouse__name",
        "creator":  "created_by__username",
        "created":  "created_at",
    }, default="created", default_order="desc")

    page_obj = _paginate(request, qs, per_page=25)
    return render(request, "admin_panel/wms/receivings/list.html", {
        "page_obj": page_obj,
        "q": q,
        "sort": sort,
        "order": order,
        "status_filter": status_filter,
        "status_choices": ReceivingStatus.choices,
        "total": qs.count(),
    })


# ─────────────────────────────────────────────────────────────
#  Задачи (обзор)
# ─────────────────────────────────────────────────────────────

@admin_required
def wms_task_list(request: HttpRequest) -> HttpResponse:
    """Обзор задач с фильтрацией и сортировкой."""
    from core.sorting import apply_ordering
    from tasks.models import Task, TaskPriority, TaskStatus, TaskType

    q = (request.GET.get("q") or "").strip()
    status_filter = request.GET.get("status", "")
    type_filter = request.GET.get("task_type", "")
    priority_filter = request.GET.get("priority", "")

    qs = Task.objects.select_related("assigned_to", "created_by")
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q))
    if status_filter:
        qs = qs.filter(status=status_filter)
    if type_filter:
        qs = qs.filter(task_type=type_filter)
    if priority_filter:
        qs = qs.filter(priority=priority_filter)

    qs, sort, order = apply_ordering(qs, request, {
        "title":    "title",
        "type":     "task_type",
        "status":   "status",
        "priority": "priority",
        "assignee": "assigned_to__username",
        "creator":  "created_by__username",
        "created":  "created_at",
        "due":      "due_date",
    }, default="created", default_order="desc")

    page_obj = _paginate(request, qs, per_page=25)
    return render(request, "admin_panel/wms/tasks/list.html", {
        "page_obj": page_obj,
        "q": q,
        "sort": sort,
        "order": order,
        "status_filter": status_filter,
        "type_filter": type_filter,
        "priority_filter": priority_filter,
        "status_choices": TaskStatus.choices,
        "type_choices": TaskType.choices,
        "priority_choices": TaskPriority.choices,
        "total": qs.count(),
    })



# ─────────────────────────────────────────────────────────────
#  Описание колонок для экспорта
# ─────────────────────────────────────────────────────────────

_PRODUCT_EXPORT_COLUMNS = [
    ExportColumn("SKU", lambda p: p.internal_sku),
    ExportColumn("Название", lambda p: p.name),
    ExportColumn("Бренд", lambda p: p.brand.name if p.brand_id else ""),
    ExportColumn("Категория", lambda p: p.category.name if p.category_id else ""),
    ExportColumn("OEM", lambda p: p.oem_number),
    ExportColumn("Аналог", lambda p: p.analog_number),
    ExportColumn("Штрихкод", lambda p: p.barcode),
    ExportColumn("Упаковка", lambda p: p.get_packaging_type_display()),
    ExportColumn("Вес, кг", lambda p: p.weight_kg if p.weight_kg is not None else ""),
]

_ORDER_EXPORT_COLUMNS = [
    ExportColumn("Номер", lambda o: o.number),
    ExportColumn("Статус", lambda o: o.get_status_display()),
    ExportColumn("Клиент", lambda o: getattr(o, "customer_name", "") or ""),
    ExportColumn("Создано", lambda o: o.created_at.strftime("%Y-%m-%d %H:%M") if getattr(o, "created_at", None) else ""),
    ExportColumn("Создал", lambda o: o.created_by.username if o.created_by_id else ""),
]
