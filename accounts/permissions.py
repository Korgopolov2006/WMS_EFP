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

