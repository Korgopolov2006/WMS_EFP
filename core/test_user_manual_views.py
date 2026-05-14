"""
Тесты для core/views.py — user_manual и user_manual_download.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from accounts.constants import Roles


User = get_user_model()


class UserManualTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="manual_admin", email="ma@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.ADMIN, is_superuser=True,
        )
        cls.storekeeper = User.objects.create_user(
            username="manual_stk", email="ms@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.STOREKEEPER,
        )
        cls.analyst = User.objects.create_user(
            username="manual_an", email="man@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.ANALYST,
        )

    def _client(self, user):
        c = Client()
        c.force_login(user)
        return c

    # ── GET /manual/ ──────────────────────────────────────────────
    def test_admin_sees_manual(self):
        client = self._client(self.admin)
        response = client.get(reverse("user_manual"))
        self.assertEqual(response.status_code, 200)

    def test_storekeeper_sees_manual(self):
        client = self._client(self.storekeeper)
        response = client.get(reverse("user_manual"))
        self.assertEqual(response.status_code, 200)

    def test_anonymous_redirected(self):
        client = Client()
        response = client.get(reverse("user_manual"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    # ── GET /manual/download/ (PDF) ───────────────────────────────
    def test_pdf_download_default_role(self):
        client = self._client(self.storekeeper)
        response = client.get(reverse("user_manual_download"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment", response.get("Content-Disposition", "").lower())

    def test_pdf_download_with_explicit_role(self):
        client = self._client(self.admin)
        response = client.get(reverse("user_manual_download"), {"role": "STOREKEEPER"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        # Имя файла содержит код роли
        self.assertIn("storekeeper", response["Content-Disposition"].lower())

    def test_pdf_download_unknown_role_uses_user_role(self):
        client = self._client(self.analyst)
        response = client.get(reverse("user_manual_download"), {"role": "BOGUS"})
        self.assertEqual(response.status_code, 200)
        # должно скачаться pdf для роли analyst
        self.assertIn("analyst", response["Content-Disposition"].lower())


class IntegrationsViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="i_admin", email="i_a@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.ADMIN, is_superuser=True,
        )

    def test_admin_sees_integrations(self):
        client = Client()
        client.force_login(self.admin)
        response = client.get(reverse("integrations"))
        self.assertEqual(response.status_code, 200)


class RoleRedirectViewTests(TestCase):
    """core.views.role_redirect — умный редирект после логина."""

    def test_admin_redirected_to_control_panel(self):
        admin = User.objects.create_user(
            username="rr_admin", email="rra@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.ADMIN, is_superuser=True,
        )
        client = Client()
        client.force_login(admin)
        response = client.get(reverse("role_redirect"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/control/", response["Location"])

    def test_regular_user_redirected_to_dashboard(self):
        user = User.objects.create_user(
            username="rr_user", email="rru@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.STOREKEEPER,
        )
        client = Client()
        client.force_login(user)
        response = client.get(reverse("role_redirect"))
        self.assertEqual(response.status_code, 302)
        # Дашборд это "/"
        self.assertIn(response["Location"], ("/", "/dashboard/"))
