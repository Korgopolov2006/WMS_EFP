"""
Интеграционные тесты views административной панели.
Покрытие: редиректы по ролям, CRUD пользователей, бэкапы, аудит, доступ.
"""
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from admin_panel.models import AuditLog, BackupRecord

User = get_user_model()


def make_admin(**kwargs) -> User:
    defaults = dict(username="admin_view", email="admin_view@test.ru",
                    password="AdminPass1!XYZW", role="ADMIN", is_active=True)
    defaults.update(kwargs)
    return User.objects.create_user(**defaults)


def make_user(**kwargs) -> User:
    defaults = dict(username="regular_view", email="regular@test.ru",
                    password="RegPass1!XYZWAB", role="STOREKEEPER", is_active=True)
    defaults.update(kwargs)
    return User.objects.create_user(**defaults)


# ─────────────────────────────────────────────────────────────
#  Авторизация и редирект по роли
# ─────────────────────────────────────────────────────────────

class TestRoleRedirect(TestCase):

    def test_admin_redirected_to_control_panel(self):
        admin = make_admin()
        self.client.force_login(admin)
        resp = self.client.get(reverse("role_redirect"))
        self.assertRedirects(resp, reverse("admin_panel:dashboard"), fetch_redirect_response=False)

    def test_regular_user_redirected_to_dashboard(self):
        user = make_user()
        self.client.force_login(user)
        resp = self.client.get(reverse("role_redirect"))
        self.assertRedirects(resp, reverse("dashboard"), fetch_redirect_response=False)

    def test_anonymous_redirected_to_login(self):
        resp = self.client.get(reverse("role_redirect"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login/", resp["Location"])


# ─────────────────────────────────────────────────────────────
#  Защита доступа (@admin_required)
# ─────────────────────────────────────────────────────────────

class TestAdminRequiredAccess(TestCase):

    PROTECTED_URLS = [
        "admin_panel:dashboard",
        "admin_panel:user_list",
        "admin_panel:user_create",
        "admin_panel:audit_list",
        "admin_panel:backup_list",
        "admin_panel:settings",
    ]

    def test_anonymous_gets_redirect_to_login(self):
        for url_name in self.PROTECTED_URLS:
            with self.subTest(url=url_name):
                resp = self.client.get(reverse(url_name))
                self.assertIn(resp.status_code, (302, 403),
                              f"{url_name}: ожидался редирект или 403")

    def test_non_admin_gets_403(self):
        user = make_user(username="non_admin_access", email="na@test.ru")
        self.client.force_login(user)
        for url_name in self.PROTECTED_URLS:
            with self.subTest(url=url_name):
                resp = self.client.get(reverse(url_name))
                self.assertEqual(resp.status_code, 403,
                                 f"{url_name}: ожидался 403 для не-администратора")

    def test_admin_gets_200(self):
        admin = make_admin(username="admin_access", email="aa@test.ru")
        self.client.force_login(admin)
        for url_name in self.PROTECTED_URLS:
            with self.subTest(url=url_name):
                resp = self.client.get(reverse(url_name))
                self.assertEqual(resp.status_code, 200,
                                 f"{url_name}: ожидался 200 для администратора")

    def test_superuser_gets_200(self):
        superuser = User.objects.create_superuser(
            username="superuser_access", email="su@test.ru", password="SuPass1!XYZWAB"
        )
        self.client.force_login(superuser)
        resp = self.client.get(reverse("admin_panel:dashboard"))
        self.assertEqual(resp.status_code, 200)


# ─────────────────────────────────────────────────────────────
#  Дашборд панели управления
# ─────────────────────────────────────────────────────────────

class TestAdminDashboard(TestCase):

    def setUp(self):
        self.admin = make_admin(username="dash_admin", email="da@test.ru")
        self.client.force_login(self.admin)

    def test_dashboard_renders(self):
        resp = self.client.get(reverse("admin_panel:dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Панель управления")

    def test_dashboard_contains_stats(self):
        resp = self.client.get(reverse("admin_panel:dashboard"))
        self.assertIn("stats", resp.context)

    def test_dashboard_contains_recent_audit(self):
        resp = self.client.get(reverse("admin_panel:dashboard"))
        self.assertIn("recent_audit", resp.context)


# ─────────────────────────────────────────────────────────────
#  Список пользователей
# ─────────────────────────────────────────────────────────────

class TestUserList(TestCase):

    def setUp(self):
        self.admin = make_admin(username="list_admin", email="la@test.ru")
        self.client.force_login(self.admin)
        make_user(username="list_user1", email="lu1@test.ru")
        make_user(username="list_user2", email="lu2@test.ru", is_active=False)

    def test_lists_users(self):
        resp = self.client.get(reverse("admin_panel:user_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "list_user1")
        self.assertContains(resp, "list_user2")

    def test_search_by_username(self):
        resp = self.client.get(reverse("admin_panel:user_list"), {"q": "list_user1"})
        self.assertContains(resp, "list_user1")
        self.assertNotContains(resp, "list_user2")

    def test_filter_by_role(self):
        resp = self.client.get(reverse("admin_panel:user_list"), {"role": "STOREKEEPER"})
        self.assertContains(resp, "list_user1")

    def test_filter_active_only(self):
        resp = self.client.get(reverse("admin_panel:user_list"), {"status": "active"})
        self.assertContains(resp, "list_user1")
        self.assertNotContains(resp, "list_user2")

    def test_filter_inactive_only(self):
        resp = self.client.get(reverse("admin_panel:user_list"), {"status": "inactive"})
        self.assertNotContains(resp, "list_user1")
        self.assertContains(resp, "list_user2")


# ─────────────────────────────────────────────────────────────
#  Создание пользователя
# ─────────────────────────────────────────────────────────────

class TestUserCreate(TestCase):

    def setUp(self):
        self.admin = make_admin(username="create_admin", email="ca@test.ru")
        self.client.force_login(self.admin)

    def test_get_renders_form(self):
        resp = self.client.get(reverse("admin_panel:user_create"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Создать пользователя")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_post_creates_user(self):
        resp = self.client.post(reverse("admin_panel:user_create"), {
            "username": "created_user",
            "email": "created@test.ru",
            "first_name": "Иван",
            "last_name": "Тест",
            "role": "LOADER",
            "branches": [],
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(User.objects.filter(username="created_user").exists())

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_post_sends_email(self):
        from django.core import mail
        self.client.post(reverse("admin_panel:user_create"), {
            "username": "email_send_user",
            "email": "emailsend@test.ru",
            "role": "ANALYST",
        })
        self.assertGreater(len(mail.outbox), 0)
        self.assertIn("emailsend@test.ru", mail.outbox[0].recipients())

    def test_post_duplicate_username_shows_error(self):
        make_user(username="dup_user", email="dup@test.ru")
        resp = self.client.post(reverse("admin_panel:user_create"), {
            "username": "dup_user",
            "email": "other@test.ru",
            "role": "LOADER",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "уже существует")

    def test_post_duplicate_email_shows_error(self):
        make_user(username="original_user", email="original@test.ru")
        resp = self.client.post(reverse("admin_panel:user_create"), {
            "username": "new_unique_user",
            "email": "original@test.ru",
            "role": "LOADER",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "уже зарегистрирован")


# ─────────────────────────────────────────────────────────────
#  Редактирование пользователя
# ─────────────────────────────────────────────────────────────

class TestUserEdit(TestCase):

    def setUp(self):
        self.admin = make_admin(username="edit_admin", email="ea@test.ru")
        self.target = make_user(username="edit_target", email="target_edit@test.ru")
        self.client.force_login(self.admin)

    def test_get_renders_form(self):
        resp = self.client.get(reverse("admin_panel:user_edit", args=[self.target.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "edit_target")

    def test_post_updates_role(self):
        resp = self.client.post(
            reverse("admin_panel:user_edit", args=[self.target.pk]),
            {
                "first_name": "Иван",
                "last_name": "Тест",
                "email": "target_edit@test.ru",
                "role": "ANALYST",
                "is_active": True,
                "branches": [],
            },
        )
        self.assertRedirects(resp, reverse("admin_panel:user_detail", args=[self.target.pk]),
                              fetch_redirect_response=False)
        self.target.refresh_from_db()
        self.assertEqual(self.target.role, "ANALYST")

    def test_cannot_edit_self(self):
        resp = self.client.get(reverse("admin_panel:user_edit", args=[self.admin.pk]))
        self.assertRedirects(resp, reverse("admin_panel:user_detail", args=[self.admin.pk]),
                              fetch_redirect_response=False)


# ─────────────────────────────────────────────────────────────
#  Блокировка / активация
# ─────────────────────────────────────────────────────────────

class TestUserToggleActive(TestCase):

    def setUp(self):
        self.admin = make_admin(username="toggle_admin", email="ta@test.ru")
        self.target = make_user(username="toggle_target", email="toggle@test.ru", is_active=True)
        self.client.force_login(self.admin)

    def test_deactivate_user(self):
        self.client.post(reverse("admin_panel:user_toggle_active", args=[self.target.pk]))
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)

    def test_activate_user(self):
        self.target.is_active = False
        self.target.save()
        self.client.post(reverse("admin_panel:user_toggle_active", args=[self.target.pk]))
        self.target.refresh_from_db()
        self.assertTrue(self.target.is_active)

    def test_cannot_deactivate_self(self):
        resp = self.client.post(reverse("admin_panel:user_toggle_active", args=[self.admin.pk]))
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_creates_audit_log(self):
        self.client.post(reverse("admin_panel:user_toggle_active", args=[self.target.pk]))
        exists = AuditLog.objects.filter(
            resource_type="User",
            resource_id=str(self.target.pk),
        ).exists()
        self.assertTrue(exists)

    def test_get_not_allowed(self):
        resp = self.client.get(reverse("admin_panel:user_toggle_active", args=[self.target.pk]))
        self.assertEqual(resp.status_code, 405)


# ─────────────────────────────────────────────────────────────
#  Удаление пользователя
# ─────────────────────────────────────────────────────────────

class TestUserDelete(TestCase):

    def setUp(self):
        self.admin = make_admin(username="del_admin", email="del_admin@test.ru")
        self.target = make_user(username="del_target", email="del_target@test.ru")
        self.client.force_login(self.admin)

    def test_get_shows_confirm_page(self):
        resp = self.client.get(reverse("admin_panel:user_delete", args=[self.target.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "необратимо")

    def test_post_deletes_user(self):
        target_pk = self.target.pk
        self.client.post(reverse("admin_panel:user_delete", args=[target_pk]))
        self.assertFalse(User.objects.filter(pk=target_pk).exists())

    def test_cannot_delete_self(self):
        resp = self.client.post(reverse("admin_panel:user_delete", args=[self.admin.pk]))
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())

    def test_creates_audit_log_on_delete(self):
        target_pk = self.target.pk
        self.client.post(reverse("admin_panel:user_delete", args=[target_pk]))
        exists = AuditLog.objects.filter(
            action=AuditLog.ActionType.DELETE,
            resource_id=str(target_pk),
        ).exists()
        self.assertTrue(exists)


# ─────────────────────────────────────────────────────────────
#  Сброс пароля через view
# ─────────────────────────────────────────────────────────────

class TestUserResetPasswordView(TestCase):

    def setUp(self):
        self.admin = make_admin(username="rp_admin", email="rp_admin@test.ru")
        self.target = make_user(username="rp_target", email="rp_target@test.ru")
        self.client.force_login(self.admin)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_post_resets_password(self):
        old_hash = self.target.password
        self.client.post(reverse("admin_panel:user_reset_password", args=[self.target.pk]))
        self.target.refresh_from_db()
        self.assertNotEqual(self.target.password, old_hash)

    def test_get_not_allowed(self):
        resp = self.client.get(reverse("admin_panel:user_reset_password", args=[self.target.pk]))
        self.assertEqual(resp.status_code, 405)


# ─────────────────────────────────────────────────────────────
#  Журнал аудита
# ─────────────────────────────────────────────────────────────

class TestAuditLogView(TestCase):

    def setUp(self):
        self.admin = make_admin(username="audit_admin", email="audit_admin@test.ru")
        self.client.force_login(self.admin)
        AuditLog.objects.create(
            user=self.admin,
            action=AuditLog.ActionType.CREATE,
            resource_type="User",
            resource_str="testuser",
        )

    def test_renders_list(self):
        resp = self.client.get(reverse("admin_panel:audit_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "testuser")

    def test_filter_by_action(self):
        resp = self.client.get(reverse("admin_panel:audit_list"), {"action": "CREATE"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Создание")

    def test_search_by_resource(self):
        resp = self.client.get(reverse("admin_panel:audit_list"), {"q": "testuser"})
        self.assertContains(resp, "testuser")


# ─────────────────────────────────────────────────────────────
#  Резервные копии
# ─────────────────────────────────────────────────────────────

class TestBackupViews(TestCase):

    def setUp(self):
        self.admin = make_admin(username="backup_admin", email="backup_admin@test.ru")
        self.client.force_login(self.admin)

    def test_backup_list_renders(self):
        resp = self.client.get(reverse("admin_panel:backup_list"))
        self.assertEqual(resp.status_code, 200)

    @patch("admin_panel.views.create_database_backup")
    def test_backup_create_success(self, mock_backup):
        mock_record = BackupRecord(
            filename="backup_20250101_120000.sql",
            size_bytes=1024,
        )
        mock_record.pk = 1
        mock_record.size_human  # property, just call
        mock_backup.return_value = mock_record

        resp = self.client.post(reverse("admin_panel:backup_create"), {"notes": "test"})
        self.assertRedirects(resp, reverse("admin_panel:backup_list"),
                              fetch_redirect_response=False)
        mock_backup.assert_called_once()

    @patch("admin_panel.views.create_database_backup")
    def test_backup_create_failure_shows_error(self, mock_backup):
        mock_backup.side_effect = RuntimeError("pg_dump не найден")
        resp = self.client.post(reverse("admin_panel:backup_create"), {"notes": "test"})
        self.assertRedirects(resp, reverse("admin_panel:backup_list"),
                              fetch_redirect_response=False)

    @patch("admin_panel.views.upload_backup_file")
    def test_backup_upload_success(self, mock_upload):
        mock_upload.return_value = BackupRecord(filename="backup_uploaded.sql", size_bytes=10)

        resp = self.client.post(
            reverse("admin_panel:backup_upload"),
            {
                "notes": "От коллеги",
                "backup_file": SimpleUploadedFile("demo.sql", b"-- dump --"),
            },
        )

        self.assertRedirects(resp, reverse("admin_panel:backup_list"), fetch_redirect_response=False)
        mock_upload.assert_called_once()

    @patch("admin_panel.views.upload_backup_file")
    def test_backup_upload_invalid_extension(self, mock_upload):
        resp = self.client.post(
            reverse("admin_panel:backup_upload"),
            {"backup_file": SimpleUploadedFile("demo.txt", b"text")},
        )

        self.assertRedirects(resp, reverse("admin_panel:backup_list"), fetch_redirect_response=False)
        mock_upload.assert_not_called()

    def test_backup_download_missing_file_404(self):
        resp = self.client.get(
            reverse("admin_panel:backup_download", args=["nonexistent.sql"])
        )
        self.assertEqual(resp.status_code, 404)

    def test_backup_delete_get_not_allowed(self):
        resp = self.client.get(
            reverse("admin_panel:backup_delete", args=["some.sql"])
        )
        self.assertEqual(resp.status_code, 405)

    def test_backup_restore_without_confirm(self):
        resp = self.client.post(
            reverse("admin_panel:backup_restore", args=["some.sql"]),
            {},
        )
        # редирект с предупреждением
        self.assertRedirects(resp, reverse("admin_panel:backup_list"),
                              fetch_redirect_response=False)


# ─────────────────────────────────────────────────────────────
#  Настройки системы
# ─────────────────────────────────────────────────────────────

class TestSystemSettings(TestCase):

    def setUp(self):
        self.admin = make_admin(username="settings_admin", email="settings_admin@test.ru")
        self.client.force_login(self.admin)

    def test_renders_settings_page(self):
        resp = self.client.get(reverse("admin_panel:settings"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Django")

    def test_contains_db_info(self):
        resp = self.client.get(reverse("admin_panel:settings"))
        self.assertIn("db_info", resp.context)

    def test_non_admin_denied(self):
        user = make_user(username="settings_user", email="su2@test.ru")
        self.client.force_login(user)
        resp = self.client.get(reverse("admin_panel:settings"))
        self.assertEqual(resp.status_code, 403)


# ─────────────────────────────────────────────────────────────
#  user_detail — одноразовые учётные данные из сессии
# ─────────────────────────────────────────────────────────────

class TestUserDetailSessionCredentials(TestCase):

    def setUp(self):
        self.admin = make_admin(username="detail_admin", email="detail_admin@test.ru")
        self.target = make_user(username="detail_target", email="detail_target@test.ru")
        self.client.force_login(self.admin)

    def test_detail_renders(self):
        resp = self.client.get(reverse("admin_panel:user_detail", args=[self.target.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "detail_target")

    def test_credentials_shown_once_from_session(self):
        """Пароль в сессии показывается один раз и удаляется."""
        session = self.client.session
        session["new_user_password"] = {
            "username": "detail_target",
            "password": "TestPass1!ABCDEF",
            "email": "detail_target@test.ru",
        }
        session.save()

        resp1 = self.client.get(reverse("admin_panel:user_detail", args=[self.target.pk]))
        self.assertIn("new_credentials", resp1.context)
        self.assertEqual(resp1.context["new_credentials"]["password"], "TestPass1!ABCDEF")

        # Второй запрос — учётных данных больше нет
        resp2 = self.client.get(reverse("admin_panel:user_detail", args=[self.target.pk]))
        self.assertIsNone(resp2.context.get("new_credentials"))

    def test_detail_shows_recent_audit(self):
        AuditLog.objects.create(
            user=self.target,
            action=AuditLog.ActionType.VIEW,
            resource_type="User",
            resource_str="detail_target",
        )
        resp = self.client.get(reverse("admin_panel:user_detail", args=[self.target.pk]))
        self.assertIn("recent_actions", resp.context)


# ─────────────────────────────────────────────────────────────
#  user_edit — отслеживание изменений role + is_active
# ─────────────────────────────────────────────────────────────

class TestUserEditChangesAuditTracking(TestCase):
    """Покрывает ветки изменения роли (строка 185) и is_active (строка 187)."""

    def setUp(self):
        self.admin = make_admin(username="track_admin", email="track_admin@test.ru")
        self.target = make_user(
            username="track_target",
            email="track_target@test.ru",
            role="STOREKEEPER",
        )
        self.client.force_login(self.admin)

    def test_role_change_recorded_in_audit(self):
        self.client.post(
            reverse("admin_panel:user_edit", args=[self.target.pk]),
            {
                "first_name": "",
                "last_name": "",
                "email": "track_target@test.ru",
                "role": "ANALYST",       # изменилась роль
                "is_active": True,
                "branches": [],
            },
        )
        self.target.refresh_from_db()
        self.assertEqual(self.target.role, "ANALYST")
        audit = AuditLog.objects.filter(
            action=AuditLog.ActionType.UPDATE,
            resource_id=str(self.target.pk),
        ).first()
        self.assertIsNotNone(audit)
        self.assertIn("role", audit.changes or {})

    def test_deactivation_recorded_in_audit(self):
        self.client.post(
            reverse("admin_panel:user_edit", args=[self.target.pk]),
            {
                "first_name": "",
                "last_name": "",
                "email": "track_target@test.ru",
                "role": "STOREKEEPER",
                "is_active": False,      # изменился статус
                "branches": [],
            },
        )
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)
        audit = AuditLog.objects.filter(
            action=AuditLog.ActionType.UPDATE,
            resource_id=str(self.target.pk),
        ).first()
        self.assertIsNotNone(audit)
        self.assertIn("is_active", audit.changes or {})

    def test_no_changes_audit_has_null_changes(self):
        """Если ничего не изменилось, changes=None в аудит-записи."""
        self.client.post(
            reverse("admin_panel:user_edit", args=[self.target.pk]),
            {
                "first_name": "",
                "last_name": "",
                "email": "track_target@test.ru",
                "role": "STOREKEEPER",  # та же роль
                "is_active": True,       # тот же статус
                "branches": [],
            },
        )
        audit = AuditLog.objects.filter(
            action=AuditLog.ActionType.UPDATE,
            resource_id=str(self.target.pk),
        ).first()
        self.assertIsNotNone(audit)
        self.assertIsNone(audit.changes)


# ─────────────────────────────────────────────────────────────
#  user_create — обработка исключения в сервисе
# ─────────────────────────────────────────────────────────────

class TestUserCreateServiceException(TestCase):
    """Покрывает строки 136-137 — except block в user_create view."""

    def setUp(self):
        self.admin = make_admin(username="exc_admin", email="exc_admin@test.ru")
        self.client.force_login(self.admin)

    @patch("admin_panel.views.create_user_with_credentials",
           side_effect=RuntimeError("DB error"))
    def test_exception_shows_error_message(self, mock_create):
        resp = self.client.post(reverse("admin_panel:user_create"), {
            "username": "exc_user",
            "email": "exc_user@test.ru",
            "role": "LOADER",
        })
        # Форма re-рендерится с ошибкой
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Ошибка создания пользователя")


# ─────────────────────────────────────────────────────────────
#  Журнал аудита — фильтр по пользователю (строка 320)
# ─────────────────────────────────────────────────────────────

class TestAuditLogUserIdFilter(TestCase):

    def setUp(self):
        self.admin = make_admin(username="audit_uid_admin", email="auid_admin@test.ru")
        self.other = make_user(username="audit_uid_other", email="auid_other@test.ru")
        self.client.force_login(self.admin)

        AuditLog.objects.create(
            user=self.admin,
            action=AuditLog.ActionType.CREATE,
            resource_type="User",
            resource_str="admin_action",
        )
        AuditLog.objects.create(
            user=self.other,
            action=AuditLog.ActionType.VIEW,
            resource_type="User",
            resource_str="other_action",
        )

    def test_filter_by_user_id_shows_only_that_user(self):
        resp = self.client.get(
            reverse("admin_panel:audit_list"),
            {"user_id": str(self.other.pk)},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "other_action")
        self.assertNotContains(resp, "admin_action")


# ─────────────────────────────────────────────────────────────
#  Бэкапы — дополнительные сценарии
# ─────────────────────────────────────────────────────────────

class TestBackupCreateInvalidForm(TestCase):
    """Строка 371: некорректная форма бэкапа."""

    def setUp(self):
        self.admin = make_admin(username="backup_inv_admin", email="bk_inv@test.ru")
        self.client.force_login(self.admin)

    def test_invalid_form_redirects_with_error(self):
        # notes > 500 символов делает форму невалидной
        resp = self.client.post(
            reverse("admin_panel:backup_create"),
            {"notes": "x" * 501},
        )
        self.assertRedirects(resp, reverse("admin_panel:backup_list"),
                              fetch_redirect_response=False)


class TestBackupDownloadPathTraversal(TestCase):
    """Строки 381-382: ValueError при path traversal → 404.

    Слэши не допустимы в URL-сегменте, поэтому мы
    патчим _safe_backup_path напрямую, имитируя атаку.
    """

    def setUp(self):
        self.admin = make_admin(username="dl_pt_admin", email="dl_pt@test.ru")
        self.client.force_login(self.admin)

    @patch("admin_panel.services._safe_backup_path",
           side_effect=ValueError("path traversal detected"))
    def test_path_traversal_returns_404(self, mock_path):
        # Передаём любое допустимое по URL имя файла;
        # _safe_backup_path «обнаружит атаку» через мок.
        resp = self.client.get(
            reverse("admin_panel:backup_download", args=["traversal_attempt.sql"])
        )
        self.assertEqual(resp.status_code, 404)


class TestBackupDownloadExistingFile(TestCase):
    """Строки 387-401: успешное скачивание реального файла."""

    def setUp(self):
        self.admin = make_admin(username="dl_ok_admin", email="dl_ok@test.ru")
        self.client.force_login(self.admin)

    def test_download_existing_file(self):
        # ignore_cleanup_errors=True чтобы Python не сломался на Windows
        # из-за блокировки файла открытым FileResponse-дескриптором.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            backup_file = Path(tmpdir) / "test_backup.sql"
            backup_file.write_text("-- SQL dump content --")

            with patch("admin_panel.services._safe_backup_path",
                       return_value=backup_file):
                resp = self.client.get(
                    reverse("admin_panel:backup_download", args=["test_backup.sql"])
                )

            # Читаем ответ, чтобы FileResponse закрыл дескриптор
            _ = b"".join(resp.streaming_content) if hasattr(resp, "streaming_content") else resp.content
            resp.close()

            self.assertEqual(resp.status_code, 200)
            self.assertIn("test_backup.sql", resp.get("Content-Disposition", ""))


class TestBackupDeleteViewPost(TestCase):
    """Строки 408-413: удаление бэкапа через POST."""

    def setUp(self):
        self.admin = make_admin(username="del_bk_admin", email="del_bk@test.ru")
        self.client.force_login(self.admin)

    @patch("admin_panel.views.delete_backup")
    def test_delete_backup_success(self, mock_delete):
        resp = self.client.post(
            reverse("admin_panel:backup_delete", args=["some_backup.sql"])
        )
        mock_delete.assert_called_once_with(
            filename="some_backup.sql", actor=self.admin
        )
        self.assertRedirects(resp, reverse("admin_panel:backup_list"),
                              fetch_redirect_response=False)

    @patch("admin_panel.views.delete_backup",
           side_effect=FileNotFoundError("not found"))
    def test_delete_backup_failure_shows_error(self, mock_delete):
        resp = self.client.post(
            reverse("admin_panel:backup_delete", args=["missing.sql"])
        )
        self.assertRedirects(resp, reverse("admin_panel:backup_list"),
                              fetch_redirect_response=False)


class TestBackupRestoreConfirmed(TestCase):
    """Строки 425-434: восстановление с подтверждением."""

    def setUp(self):
        self.admin = make_admin(username="restore_admin", email="restore_admin@test.ru")
        self.client.force_login(self.admin)

    @patch("admin_panel.views.restore_database_backup")
    def test_restore_with_confirm_succeeds(self, mock_restore):
        resp = self.client.post(
            reverse("admin_panel:backup_restore", args=["backup.sql"]),
            {"confirm_restore": "yes"},
        )
        mock_restore.assert_called_once()
        kwargs = mock_restore.call_args.kwargs
        self.assertEqual(kwargs["filename"], "backup.sql")
        self.assertEqual(kwargs["actor"], self.admin)
        self.assertFalse(kwargs.get("wipe_first", False))
        self.assertRedirects(resp, reverse("admin_panel:backup_list"),
                              fetch_redirect_response=False)

    @patch("admin_panel.views.restore_database_backup",
           side_effect=RuntimeError("psql error"))
    def test_restore_exception_shows_error(self, mock_restore):
        resp = self.client.post(
            reverse("admin_panel:backup_restore", args=["backup.sql"]),
            {"confirm_restore": "yes"},
        )
        self.assertRedirects(resp, reverse("admin_panel:backup_list"),
                              fetch_redirect_response=False)


# ─────────────────────────────────────────────────────────────
#  user_reset_password view — обработка исключения
# ─────────────────────────────────────────────────────────────

class TestUserResetPasswordViewException(TestCase):
    """Строки 292-293: except block при ошибке сброса пароля."""

    def setUp(self):
        self.admin = make_admin(username="rp_exc_admin", email="rp_exc_admin@test.ru")
        self.target = make_user(username="rp_exc_target", email="rp_exc_target@test.ru")
        self.client.force_login(self.admin)

    @patch("admin_panel.views.reset_user_password",
           side_effect=RuntimeError("hash error"))
    def test_exception_shows_error_and_redirects(self, mock_reset):
        resp = self.client.post(
            reverse("admin_panel:user_reset_password", args=[self.target.pk])
        )
        self.assertRedirects(resp, reverse("admin_panel:user_detail", args=[self.target.pk]),
                              fetch_redirect_response=False)
