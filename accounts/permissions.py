from __future__ import annotations

from collections.abc import Callable

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse


def role_required(*roles: str) -> Callable[[Callable[..., HttpResponse]], Callable[..., HttpResponse]]:
    """
    Декоратор для контроля доступа по роли пользователя.

    Пример:
        @role_required(Roles.ADMIN, Roles.STOREKEEPER)
        def view(...)
    """

    def decorator(view_func: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
        @login_required
        def _wrapped(request: HttpRequest, *args, **kwargs) -> HttpResponse:
            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)

            user_role = getattr(request.user, "role", None)
            if user_role in roles:
                return view_func(request, *args, **kwargs)

            raise PermissionDenied("Недостаточно прав для доступа к разделу.")

        return _wrapped

    return decorator


def requires(*actions: str, mode: str = "any") -> Callable[[Callable[..., HttpResponse]], Callable[..., HttpResponse]]:
    """
    Декоратор контроля доступа по матрице разрешений.

    Args:
        *actions: имена действий из accounts.role_permissions
        mode:    "any" (по умолчанию) — достаточно одного действия;
                 "all"                — требуются все.

    Пример:
        @requires(MANAGE_USERS)
        def user_list(...): ...

        @requires(SECTION_STOCK, EXPORT_DATA, mode="all")
        def stock_export(...): ...
    """
    from .role_permissions import user_can_all, user_can_any

    if not actions:
        raise ValueError("requires() требует хотя бы одно действие")
    if mode not in ("any", "all"):
        raise ValueError("mode должен быть 'any' или 'all'")
    check = user_can_all if mode == "all" else user_can_any

    def decorator(view_func: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
        @login_required
        def _wrapped(request: HttpRequest, *args, **kwargs) -> HttpResponse:
            if check(request.user, actions):
                return view_func(request, *args, **kwargs)
            raise PermissionDenied("Недостаточно прав для доступа к разделу.")

        return _wrapped

    return decorator

