"""
Декораторы доступа для административной панели.
"""
from __future__ import annotations

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse

from accounts.constants import Roles


def admin_required(view_func):
    """
    Декоратор: доступ только для Администратора или superuser.
    Поднимает PermissionDenied (→ 403) для авторизованных не-администраторов.
    Перенаправляет на логин для анонимных пользователей.
    """

    @login_required
    @wraps(view_func)
    def _wrapped(request: HttpRequest, *args, **kwargs) -> HttpResponse:
        user = request.user
        if user.is_superuser or getattr(user, "role", None) == Roles.ADMIN:
            return view_func(request, *args, **kwargs)
        raise PermissionDenied("Раздел доступен только администраторам.")

    return _wrapped
