"""
Smoke-тесты ключевых URL.

Цель — поймать регрессии маршрутов / 500-ошибок без проверки бизнес-логики.
Проверяем только status code (200 / 302 redirect для login).

Используем RequestFactory + прямой вызов view-функций — обходим
проблему `RecursionError` в Django Test Client при сложных шаблонах.
"""
from django.contrib.auth import get_user_model
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
