"""
Middleware для контроля доступа к служебным разделам WMS.

AdminAccessMiddleware:
    Блокирует авторизованных пользователей без роли суперпользователя
    или ADMIN от доступа к встроенной панели Django (/admin/).
    Вместо стандартной формы входа они видят стилизованную страницу 403.
"""
from __future__ import annotations

from django.core.exceptions import PermissionDenied


# Префиксы URL, закрытые для обычных сотрудников.
_ADMIN_PREFIXES: tuple[str, ...] = ("/admin/",)


class AdminAccessMiddleware:
    """
    Если пользователь уже авторизован, но не является суперпользователем
    или не имеет роли ADMIN — поднимает PermissionDenied.
    Django обработает исключение через handler403 и отдаст страницу 403.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._is_restricted(request):
            raise PermissionDenied(
                "Этот раздел доступен только уполномоченным сотрудникам с правами администратора."
            )
        return self.get_response(request)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _is_restricted(request) -> bool:
        """True — если нужно заблокировать запрос."""
        # Только авторизованные пользователи могут получить 403;
        # анонимов Django admin перенаправит на свою страницу входа сам.
        if not request.user.is_authenticated:
            return False

        # Проверяем, что запрос попадает в защищённый раздел.
        path = request.path
        if not any(path.startswith(prefix) for prefix in _ADMIN_PREFIXES):
            return False

        # Суперпользователь или администратор WMS — пропускаем.
        from accounts.constants import Roles  # ленивый импорт, избегаем циклических зависимостей
        is_admin = request.user.is_superuser or getattr(request.user, "role", None) == Roles.ADMIN
        return not is_admin
