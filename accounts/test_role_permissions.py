"""
Тесты матрицы прав, helper'ов, декоратора @requires и шаблонных фильтров.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.template import Context, Template
from django.test import RequestFactory, TestCase

from accounts.constants import Roles
from accounts.permissions import requires
from accounts.role_permissions import (
    ADMIN_PANEL,
    ALL_ACTIONS,
    EXPORT_DATA,
    MANAGE_USERS,
    ROLE_PERMISSIONS,
    SECTION_DASHBOARD,
    SECTION_PICKING,
    SECTION_REPORTS,
    SECTION_STOCK,
    user_can,
    user_can_all,
    user_can_any,
)

User = get_user_model()


def _user(role: str, **extra):
    return User.objects.create_user(
        username=f"u_{role}_{extra.pop('suffix', 'x')}",
        email=f"{role.lower()}@t.ru",
        password="Pass1!ABCDEFGH",
        role=role, **extra,
    )


class TestUserCan(TestCase):
    def test_anonymous_has_no_perms(self):
        self.assertFalse(user_can(AnonymousUser(), MANAGE_USERS))

    def test_admin_has_all(self):
        u = _user(Roles.ADMIN, suffix="all")
        for action in ALL_ACTIONS:
            self.assertTrue(user_can(u, action), f"ADMIN must have {action}")

    def test_superuser_overrides_role(self):
        u = User.objects.create_superuser(
            username="su", email="su@t.ru", password="Pass1!ABCDEFGH",
        )
        # Даже без role у суперпользователя есть всё
        self.assertTrue(user_can(u, MANAGE_USERS))
        self.assertTrue(user_can(u, ADMIN_PANEL))

    def test_storekeeper_has_stock_but_not_admin(self):
        u = _user(Roles.STOREKEEPER, suffix="sk")
        self.assertTrue(user_can(u, SECTION_STOCK))
        self.assertTrue(user_can(u, EXPORT_DATA))
        self.assertFalse(user_can(u, MANAGE_USERS))
        self.assertFalse(user_can(u, ADMIN_PANEL))

    def test_picker_has_only_picking(self):
        u = _user(Roles.SMALL_PARTS_PICKER, suffix="pk")
        self.assertTrue(user_can(u, SECTION_PICKING))
        self.assertTrue(user_can(u, SECTION_DASHBOARD))
        self.assertFalse(user_can(u, SECTION_STOCK))
        self.assertFalse(user_can(u, MANAGE_USERS))

    def test_analyst_has_reports_no_orders(self):
        u = _user(Roles.ANALYST, suffix="an")
        self.assertTrue(user_can(u, SECTION_REPORTS))
        self.assertFalse(user_can(u, MANAGE_USERS))

    def test_unknown_role(self):
        u = User.objects.create_user(
            username="ur", email="ur@t.ru", password="Pass1!ABCDEFGH", role="UNKNOWN",
        )
        self.assertFalse(user_can(u, MANAGE_USERS))
        self.assertFalse(user_can(u, SECTION_STOCK))


class TestAnyAll(TestCase):
    def test_any_true_when_one_matches(self):
        u = _user(Roles.STOREKEEPER, suffix="any")
        self.assertTrue(user_can_any(u, [MANAGE_USERS, SECTION_STOCK]))

    def test_any_false_when_none(self):
        u = _user(Roles.SMALL_PARTS_PICKER, suffix="any2")
        self.assertFalse(user_can_any(u, [MANAGE_USERS, ADMIN_PANEL]))

    def test_all_requires_every(self):
        u = _user(Roles.STOREKEEPER, suffix="all1")
        self.assertTrue(user_can_all(u, [SECTION_STOCK, EXPORT_DATA]))
        self.assertFalse(user_can_all(u, [SECTION_STOCK, MANAGE_USERS]))


class TestRequiresDecorator(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.req = self.factory.get("/protected/")

    def _decorated_view(self, *actions, mode="any"):
        @requires(*actions, mode=mode)
        def view(request):
            return HttpResponse("OK")
        return view

    def test_grants_when_allowed(self):
        u = _user(Roles.STOREKEEPER, suffix="dec1")
        self.req.user = u
        view = self._decorated_view(SECTION_STOCK)
        resp = view(self.req)
        self.assertEqual(resp.status_code, 200)

    def test_denies_when_not_allowed(self):
        u = _user(Roles.SMALL_PARTS_PICKER, suffix="dec2")
        self.req.user = u
        view = self._decorated_view(MANAGE_USERS)
        with self.assertRaises(PermissionDenied):
            view(self.req)

    def test_any_mode_default(self):
        u = _user(Roles.STOREKEEPER, suffix="dec3")
        self.req.user = u
        view = self._decorated_view(MANAGE_USERS, SECTION_STOCK)  # any
        resp = view(self.req)
        self.assertEqual(resp.status_code, 200)

    def test_all_mode_strict(self):
        u = _user(Roles.STOREKEEPER, suffix="dec4")
        self.req.user = u
        view = self._decorated_view(SECTION_STOCK, MANAGE_USERS, mode="all")
        with self.assertRaises(PermissionDenied):
            view(self.req)

    def test_anonymous_redirects_to_login(self):
        from django.contrib.auth.models import AnonymousUser
        self.req.user = AnonymousUser()
        view = self._decorated_view(SECTION_STOCK)
        resp = view(self.req)
        # @login_required → 302 на login
        self.assertEqual(resp.status_code, 302)

    def test_invalid_mode_raises(self):
        with self.assertRaises(ValueError):
            requires(SECTION_STOCK, mode="bogus")


class TestTemplateFilter(TestCase):
    def _render(self, template: str, user) -> str:
        return Template(template).render(Context({"user": user}))

    def test_can_filter(self):
        u = _user(Roles.STOREKEEPER, suffix="tpl1")
        out = self._render(
            '{% load role_tags %}{{ user|can:"section_stock"|yesno:"YES,NO" }}', u,
        )
        self.assertEqual(out, "YES")

    def test_can_filter_negative(self):
        u = _user(Roles.SMALL_PARTS_PICKER, suffix="tpl2")
        out = self._render(
            '{% load role_tags %}{{ user|can:"manage_users"|yesno:"YES,NO" }}', u,
        )
        self.assertEqual(out, "NO")

    def test_can_any_filter(self):
        u = _user(Roles.ANALYST, suffix="tpl3")
        out = self._render(
            '{% load role_tags %}{{ user|can_any:"manage_users,section_reports"|yesno:"YES,NO" }}', u,
        )
        self.assertEqual(out, "YES")

    def test_can_all_filter(self):
        u = _user(Roles.STOREKEEPER, suffix="tpl4")
        out = self._render(
            '{% load role_tags %}{{ user|can_all:"section_stock,export_data"|yesno:"YES,NO" }}', u,
        )
        self.assertEqual(out, "YES")
        out2 = self._render(
            '{% load role_tags %}{{ user|can_all:"section_stock,manage_users"|yesno:"YES,NO" }}', u,
        )
        self.assertEqual(out2, "NO")


class TestRoleMatrixIntegrity(TestCase):
    """Гарантирует что матрица не разъедется."""

    def test_all_roles_have_dashboard(self):
        # Каждая UI-роль должна видеть дашборд
        ui_roles = [Roles.ADMIN, Roles.STOREKEEPER, Roles.SMALL_PARTS_PICKER,
                    Roles.LOADER, Roles.SALES_MANAGER, Roles.ANALYST]
        for r in ui_roles:
            self.assertIn(SECTION_DASHBOARD, ROLE_PERMISSIONS[r], r)

    def test_only_admin_has_admin_panel(self):
        for role, perms in ROLE_PERMISSIONS.items():
            if role == Roles.ADMIN:
                self.assertIn(ADMIN_PANEL, perms)
            else:
                self.assertNotIn(ADMIN_PANEL, perms, f"{role} must not have admin_panel")

    def test_only_admin_has_manage_users(self):
        for role, perms in ROLE_PERMISSIONS.items():
            if role == Roles.ADMIN:
                self.assertIn(MANAGE_USERS, perms)
            else:
                self.assertNotIn(MANAGE_USERS, perms, f"{role} must not have manage_users")
