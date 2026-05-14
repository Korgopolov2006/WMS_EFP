"""
Тесты страниц ошибок 403 / 404 и AdminAccessMiddleware.

Покрывает:
 * permission_denied_view — рендер 403 с правильным контекстом
 * page_not_found_view — рендер 404 с путём
 * AdminAccessMiddleware — блокировка обычных пользователей от /admin/
 * Catch-all URL — кастомный 404 работает даже при DEBUG=True
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import Client, RequestFactory, TestCase

from accounts.constants import Roles
from core.middleware import AdminAccessMiddleware
from core.views import page_not_found_view, permission_denied_view


User = get_user_model()


def _dummy_response(request):
    """Заглушка для middleware get_response: возвращает 200."""
    from django.http import HttpResponse
    return HttpResponse("OK")


# ════════════════════════════════════════════════════════════════════
# permission_denied_view (handler403)
# ════════════════════════════════════════════════════════════════════
class PermissionDeniedViewTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username="denied_user", email="d@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.SMALL_PARTS_PICKER,
        )

    def test_returns_403_status(self):
        request = self.factory.get("/some/forbidden/")
        request.user = self.user
        response = permission_denied_view(request)
        self.assertEqual(response.status_code, 403)

    def test_uses_default_message_when_no_exception(self):
        request = self.factory.get("/forbidden/")
        request.user = self.user
        response = permission_denied_view(request)
        content = response.content.decode("utf-8")
        self.assertIn("Доступ закрыт", content)

    def test_propagates_exception_message(self):
        request = self.factory.get("/forbidden/")
        request.user = self.user
        exc = PermissionDenied("Только для администраторов отдела продаж")
        response = permission_denied_view(request, exception=exc)
        content = response.content.decode("utf-8")
        self.assertIn("Только для администраторов отдела продаж", content)

    def test_shows_user_role_for_authenticated(self):
        request = self.factory.get("/forbidden/")
        request.user = self.user
        response = permission_denied_view(request)
        content = response.content.decode("utf-8")
        self.assertIn("denied_user", content)


# ════════════════════════════════════════════════════════════════════
# page_not_found_view (handler404)
# ════════════════════════════════════════════════════════════════════
class PageNotFoundViewTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username="lost_user", email="l@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.STOREKEEPER,
        )

    def test_returns_404_status(self):
        request = self.factory.get("/nonexistent/")
        request.user = self.user
        response = page_not_found_view(request)
        self.assertEqual(response.status_code, 404)

    def test_includes_requested_path(self):
        request = self.factory.get("/totally-unknown-path/abc/")
        request.user = self.user
        response = page_not_found_view(request)
        content = response.content.decode("utf-8")
        self.assertIn("/totally-unknown-path/abc/", content)

    def test_title_contains_not_found_text(self):
        request = self.factory.get("/wrong/")
        request.user = self.user
        response = page_not_found_view(request)
        content = response.content.decode("utf-8")
        self.assertIn("Страница не найдена", content)


# ════════════════════════════════════════════════════════════════════
# AdminAccessMiddleware
# ════════════════════════════════════════════════════════════════════
class AdminAccessMiddlewareTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = AdminAccessMiddleware(_dummy_response)
        self.admin = User.objects.create_user(
            username="adm", email="a@t.ru", password="Pass1!ABCDEFGH",
            role=Roles.ADMIN, is_superuser=True,
        )
        self.regular = User.objects.create_user(
            username="reg", email="r@t.ru", password="Pass1!ABCDEFGH",
            role=Roles.SMALL_PARTS_PICKER,
        )
        from django.contrib.auth.models import AnonymousUser
        self.anonymous = AnonymousUser()

    def test_anonymous_passes_through(self):
        """Аноним не блокируется — пусть Django admin отрисует свою login-форму."""
        request = self.factory.get("/admin/")
        request.user = self.anonymous
        response = self.middleware(request)
        self.assertEqual(response.status_code, 200)

    def test_admin_user_passes_through(self):
        request = self.factory.get("/admin/")
        request.user = self.admin
        response = self.middleware(request)
        self.assertEqual(response.status_code, 200)

    def test_regular_user_blocked(self):
        request = self.factory.get("/admin/")
        request.user = self.regular
        with self.assertRaises(PermissionDenied):
            self.middleware(request)

    def test_non_admin_path_not_blocked(self):
        """Другие пути для обычных пользователей пропускаются."""
        request = self.factory.get("/picking/orders/")
        request.user = self.regular
        response = self.middleware(request)
        self.assertEqual(response.status_code, 200)

    def test_subpath_of_admin_also_blocked(self):
        request = self.factory.get("/admin/auth/user/")
        request.user = self.regular
        with self.assertRaises(PermissionDenied):
            self.middleware(request)


# ════════════════════════════════════════════════════════════════════
# Catch-all URL: 404 работает даже при DEBUG=True
# ════════════════════════════════════════════════════════════════════
class CatchAll404Tests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="anyone", email="any@t.ru", password="Pass1!ABCDEFGH",
            role=Roles.STOREKEEPER,
        )

    def test_unknown_path_returns_custom_404(self):
        client = Client()
        client.force_login(self.user)
        # Заведомо несуществующий путь
        response = client.get("/no/such/page/exists/")
        self.assertEqual(response.status_code, 404)
        content = response.content.decode("utf-8")
        # Используется наш шаблон, а не стандартный Django debug-404
        self.assertIn("Страница не найдена", content)
        self.assertNotIn("Using the URLconf", content)

    def test_valid_url_not_caught_by_404(self):
        client = Client()
        client.force_login(self.user)
        response = client.get("/picking/orders/")
        self.assertEqual(response.status_code, 200)


# ════════════════════════════════════════════════════════════════════
# Интеграция: реальный 403 через role_required
# ════════════════════════════════════════════════════════════════════
class RoleRequired403IntegrationTests(TestCase):
    def setUp(self):
        # Менеджер по продажам — у него нет доступа к админ-панели
        self.user = User.objects.create_user(
            username="sales1", email="s@t.ru", password="Pass1!ABCDEFGH",
            role=Roles.SALES_MANAGER,
        )

    def test_403_template_rendered_on_real_permission_denied(self):
        """
        admin_panel требует role=ADMIN. Sales manager → 403 со стилизованной страницей.
        """
        client = Client()
        client.force_login(self.user)
        response = client.get("/control/")
        self.assertEqual(response.status_code, 403)
        content = response.content.decode("utf-8")
        self.assertIn("Доступ закрыт", content)
