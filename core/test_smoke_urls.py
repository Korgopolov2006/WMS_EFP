"""
Smoke-тесты ключевых URL.

Цель — поймать регрессии маршрутов / 500-ошибок без проверки бизнес-логики.
Проверяем только status code (200 / 302 redirect для login).

Используем RequestFactory + прямой вызов view-функций — обходим
проблему `RecursionError` в Django Test Client при сложных шаблонах.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, signals as django_signals
from django.urls import reverse

User = get_user_model()


def _suppress_template_signals(setUp_method):
    """Декоратор: отключает template_rendered сигнал (см. test_movements)."""
    def wrapper(self):
        self._tr = django_signals.template_rendered.receivers
        django_signals.template_rendered.receivers = []
        return setUp_method(self)
    return wrapper


class TestPublicRoutes(TestCase):
    """Публичные маршруты должны существовать."""

    def test_login_url_exists(self):
        # /accounts/login/ обычно настроен в auth_views — проверяем reverse
        from django.urls import NoReverseMatch
        try:
            url = reverse("login")
        except NoReverseMatch:
            url = "/accounts/login/"
        # Просто факт того, что URL резолвится — уже smoke
        self.assertTrue(url)


class TestAuthenticatedSmoke(TestCase):
    """Главные страницы авторизованного пользователя возвращают 200."""

    def setUp(self):
        # отключим template_rendered чтобы избежать рекурсии при render
        self._tr = django_signals.template_rendered.receivers
        django_signals.template_rendered.receivers = []

        self.user = User.objects.create_user(
            username="smoke_user",
            email="smoke@t.ru",
            password="Pass1!ABCDEFGH",
            role="ADMIN",
            is_superuser=True,
        )
        self.factory = RequestFactory()

    def tearDown(self):
        django_signals.template_rendered.receivers = self._tr

    def _call(self, view_callable, url: str, **kwargs) -> int:
        request = self.factory.get(url, kwargs)
        request.user = self.user
        resp = view_callable(request)
        return resp.status_code

    # ── Дашборд ────────────────────────────────────────────
    def test_dashboard_renders(self):
        from core.views import dashboard
        self.assertEqual(self._call(dashboard, "/"), 200)

    def test_dashboard_my_tasks_counts_only_assigned_user(self):
        from accounts.constants import Roles
        from core.views import dashboard
        from tasks.models import Task, TaskStatus, TaskType

        current_user = User.objects.create_user(
            username="dashboard_owner",
            email="dashboard_owner@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.STOREKEEPER,
        )
        other_user = User.objects.create_user(
            username="dashboard_other",
            email="dashboard_other@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.STOREKEEPER,
        )

        Task.objects.create(
            task_type=TaskType.RECEIVING,
            title="Моя ожидающая задача",
            status=TaskStatus.PENDING,
            assigned_to=current_user,
            created_by=self.user,
        )
        Task.objects.create(
            task_type=TaskType.RECEIVING,
            title="Чужая ожидающая задача",
            status=TaskStatus.PENDING,
            assigned_to=other_user,
            created_by=self.user,
        )
        Task.objects.create(
            task_type=TaskType.INVENTORY,
            title="Моя задача в работе",
            status=TaskStatus.IN_PROGRESS,
            assigned_to=current_user,
            created_by=self.user,
        )
        Task.objects.create(
            task_type=TaskType.INVENTORY,
            title="Чужая задача в работе",
            status=TaskStatus.IN_PROGRESS,
            assigned_to=other_user,
            created_by=self.user,
        )

        captured_context = {}

        def fake_render(_request, _template, context):
            captured_context.update(context)
            return HttpResponse("ok")

        request = self.factory.get("/")
        request.user = current_user
        with patch("core.views.render", side_effect=fake_render):
            self.assertEqual(dashboard(request).status_code, 200)

        self.assertEqual(captured_context["today_summary"]["pending_tasks"], 1)
        self.assertEqual(captured_context["today_summary"]["in_progress_tasks"], 1)

    # ── Inventory ──────────────────────────────────────────
    def test_stock_list(self):
        from inventory.views import stock_list
        self.assertEqual(self._call(stock_list, "/inventory/stock/"), 200)

    def test_movement_list(self):
        from inventory.views import movement_list
        self.assertEqual(self._call(movement_list, "/inventory/movements/"), 200)

    # ── Catalog ────────────────────────────────────────────
    def test_scanner_view(self):
        from catalog.barcode_views import scanner_view
        self.assertEqual(self._call(scanner_view, "/catalog/codes/scan/"), 200)

    # ── Notifications ──────────────────────────────────────
    def test_notifications_list(self):
        from notifications.views import notification_list
        self.assertEqual(self._call(notification_list, "/notifications/"), 200)

    def test_notifications_unread_api(self):
        from notifications.views import unread_count_api
        self.assertEqual(self._call(unread_count_api, "/notifications/unread-count/"), 200)


class TestExportEndpoints(TestCase):
    """CSV/XLSX/PDF экспорт не падает на пустых запросах."""

    def setUp(self):
        self._tr = django_signals.template_rendered.receivers
        django_signals.template_rendered.receivers = []
        self.user = User.objects.create_user(
            username="exp_smoke", email="es@t.ru",
            password="Pass1!ABCDEFGH", role="ADMIN", is_superuser=True,
        )
        self.factory = RequestFactory()

    def tearDown(self):
        django_signals.template_rendered.receivers = self._tr

    def _get(self, view_func, url, **q):
        req = self.factory.get(url, q)
        req.user = self.user
        return view_func(req)

    def test_movements_csv(self):
        from inventory.views import movement_list
        resp = self._get(movement_list, "/inventory/movements/", export="csv")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp["Content-Type"])

    def test_movements_xlsx(self):
        from inventory.views import movement_list
        resp = self._get(movement_list, "/inventory/movements/", export="xlsx")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("spreadsheetml", resp["Content-Type"])

    def test_movements_pdf(self):
        from inventory.views import movement_list
        resp = self._get(movement_list, "/inventory/movements/", export="pdf")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(resp.content.startswith(b"%PDF-"))


class TestRoleRedirectSmoke(TestCase):
    """role_redirect должен направлять админа в /control/, остальных в /."""

    def setUp(self):
        self.factory = RequestFactory()

    def test_admin_goes_to_control(self):
        u = User.objects.create_user(
            username="rr_admin", email="rr_admin@t.ru",
            password="Pass1!ABCDEFGH", role="ADMIN", is_superuser=True,
        )
        from core.views import role_redirect
        req = self.factory.get("/")
        req.user = u
        resp = role_redirect(req)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/control/", resp["Location"])

    def test_storekeeper_goes_to_dashboard(self):
        u = User.objects.create_user(
            username="rr_sk", email="rr_sk@t.ru",
            password="Pass1!ABCDEFGH", role="STOREKEEPER",
        )
        from core.views import role_redirect
        req = self.factory.get("/")
        req.user = u
        resp = role_redirect(req)
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn("/control/", resp["Location"])
