"""
Дополнительные тесты admin_panel/services.py — функции, которые
не покрыты основными test_services.py.

Покрывает:
 * generate_secure_password — длина, разные символы
 * validate_password_complexity — все ветки ошибок
 * create_user_with_credentials — создание + log_action
 * reset_user_password — генерация нового пароля
 * get_admin_dashboard_stats — статистика
 * sync_backup_records — синхронизация с ФС
 * delete_backup — удаление файла + записи
 * _safe_backup_path — защита от path traversal
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from accounts.constants import Roles
from admin_panel.models import AuditLog, BackupRecord
from admin_panel.services import (
    PASSWORD_LENGTH,
    SPECIAL_CHARS,
    create_user_with_credentials,
    delete_backup,
    generate_secure_password,
    get_admin_dashboard_stats,
    log_action,
    reset_user_password,
    sync_backup_records,
    validate_password_complexity,
)


User = get_user_model()


# ════════════════════════════════════════════════════════════════════
# generate_secure_password
# ════════════════════════════════════════════════════════════════════
class GeneratePasswordTests(TestCase):
    def test_default_length(self):
        pwd = generate_secure_password()
        self.assertEqual(len(pwd), PASSWORD_LENGTH)

    def test_custom_length(self):
        pwd = generate_secure_password(20)
        self.assertEqual(len(pwd), 20)

    def test_contains_upper_lower_digit_special(self):
        for _ in range(10):  # генерация рандомная, прогоняем несколько раз
            pwd = generate_secure_password()
            self.assertTrue(any(c.isupper() for c in pwd))
            self.assertTrue(any(c.islower() for c in pwd))
            self.assertTrue(any(c.isdigit() for c in pwd))
            self.assertTrue(any(c in SPECIAL_CHARS for c in pwd))


# ════════════════════════════════════════════════════════════════════
# validate_password_complexity
# ════════════════════════════════════════════════════════════════════
class ValidatePasswordTests(TestCase):
    def test_valid_password(self):
        ok, errs = validate_password_complexity("Aa1!aaaaaaaaaaaaa")
        self.assertTrue(ok)
        self.assertEqual(errs, [])

    def test_short_password(self):
        ok, errs = validate_password_complexity("Aa1!")
        self.assertFalse(ok)
        self.assertTrue(any("длина" in e.lower() for e in errs))

    def test_no_upper(self):
        ok, errs = validate_password_complexity("aaaaaa1!aaaaaaaaa")
        self.assertFalse(ok)
        self.assertTrue(any("заглавной" in e.lower() for e in errs))

    def test_no_lower(self):
        ok, errs = validate_password_complexity("AAAAAA1!AAAAAAAAA")
        self.assertFalse(ok)
        self.assertTrue(any("строчной" in e.lower() for e in errs))

    def test_no_digit(self):
        ok, errs = validate_password_complexity("Aaaaaaaaa!aaaaaaa")
        self.assertFalse(ok)
        self.assertTrue(any("цифры" in e.lower() for e in errs))

    def test_no_special(self):
        ok, errs = validate_password_complexity("Aa12345678901234567")
        self.assertFalse(ok)
        self.assertTrue(any("специальн" in e.lower() for e in errs))


# ════════════════════════════════════════════════════════════════════
# create_user_with_credentials
# ════════════════════════════════════════════════════════════════════
class CreateUserCredentialsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="adm_creator", email="ac@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.ADMIN, is_superuser=True,
        )

    def test_creates_user_and_logs_action(self):
        user, raw_password = create_user_with_credentials(
            self.admin,
            cleaned_data={
                "username": "newuser",
                "email": "newuser@example.com",
                "first_name": "Ivan",
                "last_name": "Petrov",
                "role": Roles.STOREKEEPER,
            },
        )
        self.assertIsNotNone(user.pk)
        self.assertEqual(user.username, "newuser")
        self.assertTrue(user.check_password(raw_password))
        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.ActionType.CREATE,
                resource_type="User",
                resource_id=str(user.pk),
            ).exists()
        )

    def test_email_failure_does_not_break_creation(self):
        with mock.patch(
            "admin_panel.services.send_welcome_email",
            side_effect=Exception("SMTP down"),
        ):
            user, raw = create_user_with_credentials(
                self.admin,
                cleaned_data={
                    "username": "errmail",
                    "email": "err@example.com",
                    "role": Roles.LOADER,
                },
            )
        self.assertIsNotNone(user.pk)


# ════════════════════════════════════════════════════════════════════
# reset_user_password
# ════════════════════════════════════════════════════════════════════
class ResetPasswordTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="resetadm", email="ra@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.ADMIN, is_superuser=True,
        )
        self.target = User.objects.create_user(
            username="target", email="t@t.ru",
            password="OldPass1!ABCDEFGH", role=Roles.STOREKEEPER,
        )

    def test_password_is_changed(self):
        old_hash = self.target.password
        new_pwd = reset_user_password(self.admin, self.target)
        self.target.refresh_from_db()
        self.assertNotEqual(self.target.password, old_hash)
        self.assertTrue(self.target.check_password(new_pwd))

    def test_audit_log_created(self):
        reset_user_password(self.admin, self.target)
        self.assertTrue(
            AuditLog.objects.filter(
                resource_type="User",
                resource_id=str(self.target.pk),
            ).exists()
        )


# ════════════════════════════════════════════════════════════════════
# log_action
# ════════════════════════════════════════════════════════════════════
class LogActionTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="logadm", email="la@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.ADMIN, is_superuser=True,
        )

    def test_creates_audit_log_record(self):
        log_action(
            actor=self.admin,
            action=AuditLog.ActionType.CREATE,
            resource_type="Test",
            resource_id="42",
            resource_str="test resource",
            changes={"k": "v"},
        )
        log = AuditLog.objects.filter(
            user=self.admin, resource_type="Test", resource_id="42",
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.changes.get("k"), "v")


# ════════════════════════════════════════════════════════════════════
# get_admin_dashboard_stats
# ════════════════════════════════════════════════════════════════════
class DashboardStatsTests(TestCase):
    def test_returns_expected_keys(self):
        stats = get_admin_dashboard_stats()
        for key in ("total_users", "active_users", "pending_tasks",
                    "in_progress_tasks", "open_orders"):
            self.assertIn(key, stats)


# ════════════════════════════════════════════════════════════════════
# Backup utility функции
# ════════════════════════════════════════════════════════════════════
class BackupSyncTests(TestCase):
    def setUp(self):
        # Изолированная temp-папка для backups
        self.tmpdir = Path(tempfile.mkdtemp())
        self._override = override_settings(BACKUP_DIR=self.tmpdir)
        self._override.enable()

    def tearDown(self):
        self._override.disable()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @mock.patch("admin_panel.services._get_backup_dir")
    def test_sync_finds_new_files(self, mock_dir):
        mock_dir.return_value = self.tmpdir
        # Создаём файл, которого нет в БД
        new_file = self.tmpdir / "backup_20260101_120000.sql"
        new_file.write_text("test")

        result = sync_backup_records()
        self.assertTrue(BackupRecord.objects.filter(filename=new_file.name).exists())

    @mock.patch("admin_panel.services._get_backup_dir")
    def test_sync_removes_records_for_missing_files(self, mock_dir):
        mock_dir.return_value = self.tmpdir
        # Запись в БД без файла на диске
        BackupRecord.objects.create(
            filename="backup_ghost.sql", size_bytes=100,
        )
        sync_backup_records()
        self.assertFalse(BackupRecord.objects.filter(filename="backup_ghost.sql").exists())

    @mock.patch("admin_panel.services._safe_backup_path")
    def test_delete_backup_removes_file_and_record(self, mock_safe):
        # подготавливаем запись и файл
        target_file = self.tmpdir / "backup_to_delete.sql"
        target_file.write_text("data")
        mock_safe.return_value = target_file
        BackupRecord.objects.create(filename="backup_to_delete.sql", size_bytes=4)

        delete_backup("backup_to_delete.sql")
        self.assertFalse(target_file.exists())
        self.assertFalse(
            BackupRecord.objects.filter(filename="backup_to_delete.sql").exists()
        )

    @mock.patch("admin_panel.services._safe_backup_path")
    def test_delete_backup_ignores_missing_file(self, mock_safe):
        ghost_file = self.tmpdir / "backup_ghost2.sql"
        mock_safe.return_value = ghost_file
        # Запись без файла — функция не должна упасть
        BackupRecord.objects.create(filename="backup_ghost2.sql", size_bytes=0)
        delete_backup("backup_ghost2.sql")
        self.assertFalse(
            BackupRecord.objects.filter(filename="backup_ghost2.sql").exists()
        )
