"""
Расширенные smoke-тесты для всех ключевых GET-маршрутов WMS.

Проверяют:
 * страница рендерится (200) для авторизованного пользователя
 * аноним перенаправляется на /accounts/login/
 * страница 403 показывается без нужной роли (для защищённых)
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from accounts.constants import Roles
from catalog.models import Branch, Brand, Category, Product, Warehouse


User = get_user_model()


class SmokeViewMixin:
    """Удобный клиент с админом для прогона GET-смоук."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="smoke_admin", email="sa@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.ADMIN, is_superuser=True, is_staff=True,
        )
        cls.regular = User.objects.create_user(
            username="smoke_regular", email="sr@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.SMALL_PARTS_PICKER,
        )

    def _login(self, user=None):
        client = Client()
        client.force_login(user or self.admin)
        return client

    def _assert_get(self, client, url, expected_status=(200, 302)):
        """Проверка что GET выполнился без 500-ки."""
        response = client.get(url, follow=False)
        self.assertIn(
            response.status_code, expected_status,
            f"{url} → {response.status_code} (ожидали {expected_status})",
        )
        return response


class AuthRedirectTests(SmokeViewMixin, TestCase):
    """Аноним получает 302 на login для приватных страниц."""

    URLS = [
        "/",
        "/picking/orders/",
        "/picking/tasks/",
        "/receiving/",
        "/inventory/stock/",
        "/inventory/inventory/",
        "/inventory/movements/",
        "/tasks/",
        "/notifications/",
    ]

    def test_anonymous_redirects_to_login(self):
        client = Client()
        for url in self.URLS:
            response = client.get(url, follow=False)
            self.assertEqual(
                response.status_code, 302,
                f"{url} должен редиректить аноним → 302, получили {response.status_code}",
            )
            self.assertIn("login", response["Location"])


class AdminGetSmokeTests(SmokeViewMixin, TestCase):
    """Все главные GET-страницы открываются админом без 500."""

    URLS = [
        # core
        "/",
        "/manual/",
        "/integrations/",
        # picking
        "/picking/orders/",
        "/picking/orders/new/",
        "/picking/tasks/",
        # receiving
        "/receiving/",
        "/receiving/suppliers/",
        "/receiving/suppliers/new/",
        "/receiving/new/",
        # inventory
        "/inventory/stock/",
        "/inventory/inventory/",
        "/inventory/inventory/new/",
        "/inventory/movements/",
        # tasks
        "/tasks/",
        "/tasks/new/",
        "/tasks/monitoring/",
        # accounts
        "/accounts/me/",
        # notifications
        "/notifications/",
    ]

    def test_admin_gets_all_pages_without_500(self):
        client = self._login(self.admin)
        for url in self.URLS:
            response = self._assert_get(client, url)
            self.assertNotEqual(
                response.status_code, 500,
                f"{url} → 500 (ошибка сервера)",
            )


class RegularUserAccessTests(SmokeViewMixin, TestCase):
    """Обычный пользователь без admin-прав получает 403 на /admin/."""

    def test_picker_blocked_from_django_admin(self):
        """
        Регрессионный тест на core.middleware.AdminAccessMiddleware:
        авторизованный без is_superuser/role=ADMIN получает 403.
        """
        client = self._login(self.regular)
        response = client.get("/admin/", follow=False)
        self.assertEqual(response.status_code, 403)

    def test_admin_passes_to_django_admin(self):
        client = self._login(self.admin)
        response = client.get("/admin/", follow=False)
        # admin отдаёт 200 либо 302 (внутренний редирект на login_required)
        self.assertIn(response.status_code, (200, 302))


class NonExistentPageTests(SmokeViewMixin, TestCase):
    """Несуществующий URL → 404 (через catch-all)."""

    def test_unknown_url_returns_404(self):
        client = self._login(self.admin)
        response = client.get("/this/page/does/not/exist/", follow=False)
        self.assertEqual(response.status_code, 404)

    def test_404_template_used(self):
        client = self._login(self.admin)
        response = client.get("/random-trash-abc-123/", follow=False)
        # Кастомный шаблон содержит текст "Страница не найдена"
        self.assertEqual(response.status_code, 404)
        self.assertIn(
            "Страница не найдена",
            response.content.decode("utf-8", errors="ignore"),
        )


class DashboardContextTests(SmokeViewMixin, TestCase):
    """Дашборд должен корректно работать для каждой роли."""

    ROLES_TO_TEST = [
        Roles.STOREKEEPER,
        Roles.SMALL_PARTS_PICKER,
        Roles.LOADER,
        Roles.SALES_MANAGER,
        Roles.ANALYST,
    ]

    def test_dashboard_renders_for_each_role(self):
        for role in self.ROLES_TO_TEST:
            user = User.objects.create_user(
                username=f"dash_{role.lower()}",
                email=f"dash_{role.lower()}@t.ru",
                password="Pass1!ABCDEFGH", role=role,
            )
            client = Client()
            client.force_login(user)
            response = client.get("/", follow=False)
            self.assertEqual(
                response.status_code, 200,
                f"Дашборд для роли {role} вернул {response.status_code}",
            )
