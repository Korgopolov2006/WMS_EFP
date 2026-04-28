"""
Тесты сервисного слоя admin_panel.
Покрытие: генерация паролей, создание пользователей, аудит, бэкапы.
"""
import string
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from admin_panel.models import AuditLog
from admin_panel.services import (
    SPECIAL_CHARS,
    _safe_backup_path,
    create_user_with_credentials,
    generate_secure_password,
    log_action,
    reset_user_password,
    validate_password_complexity,
)

User = get_user_model()


# ─────────────────────────────────────────────────────────────
#  Генерация пароля
# ─────────────────────────────────────────────────────────────

class TestGenerateSecurePassword(TestCase):
    """Проверки генератора криптографически безопасного пароля."""

    def test_default_length_is_16(self):
        pwd = generate_secure_password()
        self.assertEqual(len(pwd), 16)

    def test_custom_length(self):
        pwd = generate_secure_password(length=24)
        self.assertEqual(len(pwd), 24)

    def test_contains_uppercase(self):
        for _ in range(20):
            pwd = generate_secure_password()
            self.assertTrue(any(c.isupper() for c in pwd),
                            f"Нет заглавной в: {pwd}")

    def test_contains_lowercase(self):
        for _ in range(20):
            pwd = generate_secure_password()
            self.assertTrue(any(c.islower() for c in pwd),
                            f"Нет строчной в: {pwd}")

    def test_contains_digit(self):
        for _ in range(20):
            pwd = generate_secure_password()
            self.assertTrue(any(c.isdigit() for c in pwd),
                            f"Нет цифры в: {pwd}")

    def test_contains_special_char(self):
        for _ in range(20):
            pwd = generate_secure_password()
            self.assertTrue(any(c in SPECIAL_CHARS for c in pwd),
                            f"Нет спецсимвола в: {pwd}")

    def test_passwords_are_unique(self):
        """Два вызова не должны вернуть одинаковый пароль."""
        passwords = {generate_secure_password() for _ in range(50)}
        self.assertGreater(len(passwords), 45,
                           "Слишком много коллизий паролей")

    def test_uses_only_allowed_chars(self):
        allowed = set(string.ascii_letters + string.digits + SPECIAL_CHARS)
        for _ in range(10):
            pwd = generate_secure_password()
            self.assertTrue(set(pwd).issubset(allowed),
                            f"Запрещённые символы в: {pwd}")


# ─────────────────────────────────────────────────────────────
#  Валидация сложности пароля
# ─────────────────────────────────────────────────────────────

class TestValidatePasswordComplexity(TestCase):

    def test_valid_strong_password(self):
        is_valid, errors = validate_password_complexity("Abc1!xyz2@Def3#gh")
        self.assertTrue(is_valid)
        self.assertEqual(errors, [])

    def test_too_short(self):
        is_valid, errors = validate_password_complexity("Abc1!")
        self.assertFalse(is_valid)
        self.assertTrue(any("длина" in e.lower() for e in errors))

    def test_no_uppercase(self):
        is_valid, errors = validate_password_complexity("abc1!xyz2@def3#gh")
        self.assertFalse(is_valid)
        self.assertTrue(any("заглавн" in e.lower() for e in errors))

    def test_no_lowercase(self):
        is_valid, errors = validate_password_complexity("ABC1!XYZ2@DEF3#GH")
        self.assertFalse(is_valid)
        self.assertTrue(any("строчн" in e.lower() for e in errors))

    def test_no_digit(self):
        is_valid, errors = validate_password_complexity("Abcd!Efgh@Ijkl#mn")
        self.assertFalse(is_valid)
        self.assertTrue(any("цифр" in e.lower() for e in errors))

    def test_no_special(self):
        is_valid, errors = validate_password_complexity("Abcdef12345678gh")
        self.assertFalse(is_valid)
        self.assertTrue(any("спец" in e.lower() for e in errors))

    def test_generated_password_always_valid(self):
        """Сгенерированные пароли всегда проходят валидацию."""
        for _ in range(30):
            pwd = generate_secure_password()
            is_valid, errors = validate_password_complexity(pwd)
            self.assertTrue(is_valid, f"Невалидный сгенерированный пароль: {pwd}, ошибки: {errors}")


# ─────────────────────────────────────────────────────────────
#  Создание пользователя
# ─────────────────────────────────────────────────────────────

class TestCreateUserWithCredentials(TestCase):

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="test_admin",
            email="admin@test.ru",
            password="AdminPass1!ABCDE",
        )
        from catalog.models import Branch
        self.branch = Branch.objects.create(code="TST", name="Тестовый филиал")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_creates_user(self):
        data = {
            "username": "newuser",
            "email": "newuser@test.ru",
            "first_name": "Иван",
            "last_name": "Тестов",
            "role": "STOREKEEPER",
            "branches": [],
        }
        user, raw_password = create_user_with_credentials(self.admin, data)
        self.assertIsNotNone(user.pk)
        self.assertEqual(user.username, "newuser")
        self.assertEqual(user.email, "newuser@test.ru")
        self.assertEqual(user.role, "STOREKEEPER")
        self.assertTrue(user.is_active)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_password_is_hashed(self):
        data = {
            "username": "hashtest",
            "email": "hash@test.ru",
            "role": "LOADER",
            "branches": [],
        }
        user, raw_password = create_user_with_credentials(self.admin, data)
        # Django хранит хеш, не raw пароль
        self.assertNotEqual(user.password, raw_password)
        self.assertTrue(user.check_password(raw_password))

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_raw_password_passes_complexity(self):
        data = {
            "username": "complextest",
            "email": "complex@test.ru",
            "role": "ANALYST",
            "branches": [],
        }
        _, raw_password = create_user_with_credentials(self.admin, data)
        is_valid, errors = validate_password_complexity(raw_password)
        self.assertTrue(is_valid, f"Ошибки: {errors}")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_creates_audit_log(self):
        data = {
            "username": "auditlogtest",
            "email": "auditlog@test.ru",
            "role": "SALES_MANAGER",
            "branches": [],
        }
        user, _ = create_user_with_credentials(self.admin, data)
        audit = AuditLog.objects.filter(
            action=AuditLog.ActionType.CREATE,
            resource_type="User",
            resource_id=str(user.pk),
        )
        self.assertTrue(audit.exists(), "Запись аудита не создана")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_assigns_branches(self):
        data = {
            "username": "branchtest",
            "email": "branch@test.ru",
            "role": "STOREKEEPER",
            "branches": [self.branch],
        }
        user, _ = create_user_with_credentials(self.admin, data)
        self.assertIn(self.branch, user.branches.all())

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_sends_email(self):
        from django.core import mail
        data = {
            "username": "emailtest",
            "email": "emailtest@test.ru",
            "role": "STOREKEEPER",
            "branches": [],
        }
        create_user_with_credentials(self.admin, data)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("emailtest@test.ru", mail.outbox[0].recipients())
        self.assertIn("WMS ЕФП-ПАРТС", mail.outbox[0].subject)


# ─────────────────────────────────────────────────────────────
#  Сброс пароля
# ─────────────────────────────────────────────────────────────

class TestResetUserPassword(TestCase):

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin_reset",
            email="admin_reset@test.ru",
            password="AdminPass1!ABCDE",
        )
        self.target = User.objects.create_user(
            username="target_user",
            email="target@test.ru",
            password="OldPass1!ABCDEF",
            role="LOADER",
        )

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_changes_password(self):
        old_hash = self.target.password
        reset_user_password(self.admin, self.target)
        self.target.refresh_from_db()
        self.assertNotEqual(self.target.password, old_hash)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_new_password_is_valid(self):
        raw = reset_user_password(self.admin, self.target)
        is_valid, errors = validate_password_complexity(raw)
        self.assertTrue(is_valid, f"Ошибки: {errors}")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_creates_audit_log(self):
        reset_user_password(self.admin, self.target)
        exists = AuditLog.objects.filter(
            action=AuditLog.ActionType.PASSWORD_RESET,
            resource_id=str(self.target.pk),
        ).exists()
        self.assertTrue(exists)


# ─────────────────────────────────────────────────────────────
#  Журнал аудита
# ─────────────────────────────────────────────────────────────

class TestLogAction(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="log_actor",
            email="log@test.ru",
            password="Pass1!ABCDEFGHIJ",
        )

    def test_creates_audit_record(self):
        entry = log_action(
            actor=self.user,
            action=AuditLog.ActionType.CREATE,
            resource_type="User",
            resource_id="99",
            resource_str="testuser",
        )
        self.assertIsNotNone(entry.pk)
        self.assertEqual(entry.action, AuditLog.ActionType.CREATE)
        self.assertEqual(entry.user, self.user)
        self.assertEqual(entry.resource_id, "99")

    def test_ip_from_request(self):
        mock_request = MagicMock()
        mock_request.META = {"REMOTE_ADDR": "192.168.1.1", "HTTP_USER_AGENT": "TestAgent/1.0"}
        entry = log_action(
            actor=self.user,
            action=AuditLog.ActionType.VIEW,
            request=mock_request,
        )
        self.assertEqual(entry.ip_address, "192.168.1.1")

    def test_ip_from_x_forwarded_for(self):
        mock_request = MagicMock()
        mock_request.META = {
            "HTTP_X_FORWARDED_FOR": "10.0.0.1, 172.16.0.1",
            "REMOTE_ADDR": "127.0.0.1",
            "HTTP_USER_AGENT": "",
        }
        entry = log_action(
            actor=self.user,
            action=AuditLog.ActionType.VIEW,
            request=mock_request,
        )
        self.assertEqual(entry.ip_address, "10.0.0.1")

    def test_null_actor_allowed(self):
        entry = log_action(actor=None, action=AuditLog.ActionType.BACKUP_CREATE)
        self.assertIsNone(entry.user)

    def test_changes_stored(self):
        changes = {"role": {"from": "LOADER", "to": "STOREKEEPER"}}
        entry = log_action(
            actor=self.user,
            action=AuditLog.ActionType.UPDATE,
            changes=changes,
        )
        self.assertEqual(entry.changes, changes)


# ─────────────────────────────────────────────────────────────
#  Обработка ошибок email (строки 121-122 и 151-152)
# ─────────────────────────────────────────────────────────────

class TestEmailExceptionHandling(TestCase):
    """Создание/сброс пароля не должны прерываться при ошибке почты."""

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="email_err_admin",
            email="email_err_admin@test.ru",
            password="AdminPass1!ABCDE",
        )

    @patch("admin_panel.services.send_welcome_email", side_effect=Exception("SMTP error"))
    def test_create_user_survives_email_error(self, mock_email):
        """create_user_with_credentials не поднимает исключение при ошибке email."""
        data = {
            "username": "email_err_user",
            "email": "email_err@test.ru",
            "role": "LOADER",
            "branches": [],
        }
        user, raw_password = create_user_with_credentials(self.admin, data)
        self.assertIsNotNone(user.pk)
        # email был вызван
        mock_email.assert_called_once()

    @patch("admin_panel.services.send_welcome_email", side_effect=ConnectionError("timeout"))
    def test_reset_password_survives_email_error(self, mock_email):
        """reset_user_password не поднимает исключение при ошибке email."""
        target = User.objects.create_user(
            username="reset_email_err",
            email="reset_email_err@test.ru",
            password="OldPass1!ABCDEF",
            role="ANALYST",
        )
        raw = reset_user_password(self.admin, target)
        self.assertTrue(len(raw) == 16)
        # email был вызван
        mock_email.assert_called_once()


# ─────────────────────────────────────────────────────────────
#  _safe_backup_path — защита от path traversal
# ─────────────────────────────────────────────────────────────

class TestSafeBackupPath(TestCase):

    def test_valid_filename_returns_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("admin_panel.services.BACKUP_DIR", Path(tmpdir)):
                result = _safe_backup_path("backup_test.sql")
                self.assertEqual(result, Path(tmpdir) / "backup_test.sql")

    def test_path_traversal_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # parent содержит tmpdir, поэтому атака "выходит" за пределы backup_dir
            backup_dir = Path(tmpdir) / "backups"
            backup_dir.mkdir()
            with patch("admin_panel.services.BACKUP_DIR", backup_dir):
                with self.assertRaises(ValueError):
                    _safe_backup_path("../secret.txt")

    def test_nested_path_traversal_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "backups"
            backup_dir.mkdir()
            with patch("admin_panel.services.BACKUP_DIR", backup_dir):
                with self.assertRaises(ValueError):
                    _safe_backup_path("../../etc/passwd")


# ─────────────────────────────────────────────────────────────
#  Сервисы резервных копий (pg_dump / psql / filesystem)
# ─────────────────────────────────────────────────────────────

class TestBackupServices(TestCase):
    """
    Покрывает функции работы с бэкапами (lines 271-401 services.py).
    subprocess.run мокируется, чтобы не требовать реального PostgreSQL.
    """

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="bk_svc_admin",
            email="bk_svc_admin@test.ru",
            password="AdminPass1!ABCDE",
        )
        self.tmpdir = tempfile.mkdtemp()
        self.backup_dir = Path(self.tmpdir) / "backups"
        self.backup_dir.mkdir()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ── create_database_backup ────────────────────────────────

    @patch("admin_panel.services.subprocess.run")
    def test_create_backup_success(self, mock_run):
        from admin_panel.services import create_database_backup

        mock_run.return_value.returncode = 0

        with patch("admin_panel.services.BACKUP_DIR", self.backup_dir):
            # Создаём фиктивный файл, который «создал» pg_dump
            def fake_run(cmd, **kw):
                # создаём файл, на который ссылается cmd[-1]
                Path(cmd[-1]).write_text("-- fake dump --")
                result = MagicMock()
                result.returncode = 0
                return result

            mock_run.side_effect = fake_run
            record = create_database_backup(created_by=self.admin, notes="test")

        self.assertIsNotNone(record.pk)
        self.assertTrue(record.filename.startswith("backup_"))
        self.assertEqual(record.notes, "test")
        self.assertFalse(record.is_auto)

    @patch("admin_panel.services.subprocess.run")
    def test_create_backup_auto_flag(self, mock_run):
        from admin_panel.services import create_database_backup

        def fake_run(cmd, **kw):
            Path(cmd[-1]).write_text("-- dump --")
            result = MagicMock()
            result.returncode = 0
            return result

        mock_run.side_effect = fake_run

        with patch("admin_panel.services.BACKUP_DIR", self.backup_dir):
            record = create_database_backup(is_auto=True)

        self.assertTrue(record.is_auto)

    @patch("admin_panel.services.subprocess.run")
    def test_create_backup_pg_dump_failure_raises(self, mock_run):
        from admin_panel.services import create_database_backup

        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "connection refused"

        with patch("admin_panel.services.BACKUP_DIR", self.backup_dir):
            with self.assertRaises(RuntimeError) as ctx:
                create_database_backup()
        self.assertIn("pg_dump", str(ctx.exception))

    @patch("admin_panel.services.subprocess.run")
    def test_create_backup_creates_audit_log(self, mock_run):
        from admin_panel.models import AuditLog
        from admin_panel.services import create_database_backup

        def fake_run(cmd, **kw):
            Path(cmd[-1]).write_text("-- dump --")
            result = MagicMock()
            result.returncode = 0
            return result

        mock_run.side_effect = fake_run

        with patch("admin_panel.services.BACKUP_DIR", self.backup_dir):
            record = create_database_backup(created_by=self.admin)

        exists = AuditLog.objects.filter(
            action=AuditLog.ActionType.BACKUP_CREATE,
            resource_str=record.filename,
        ).exists()
        self.assertTrue(exists)

    # ── sync_backup_records ───────────────────────────────────

    def test_sync_adds_new_file_records(self):
        from admin_panel.services import sync_backup_records
        from admin_panel.models import BackupRecord

        # Создаём файл резервной копии в tmpdir (без DB записи)
        fake_file = self.backup_dir / "backup_20250101_000000.sql"
        fake_file.write_text("-- sql --")

        with patch("admin_panel.services.BACKUP_DIR", self.backup_dir):
            sync_backup_records()

        self.assertTrue(
            BackupRecord.objects.filter(filename="backup_20250101_000000.sql").exists()
        )

    def test_sync_removes_stale_db_records(self):
        from admin_panel.services import sync_backup_records
        from admin_panel.models import BackupRecord

        # Запись в DB есть, файла нет
        BackupRecord.objects.create(
            filename="stale_backup.sql",
            size_bytes=0,
        )

        with patch("admin_panel.services.BACKUP_DIR", self.backup_dir):
            sync_backup_records()

        self.assertFalse(
            BackupRecord.objects.filter(filename="stale_backup.sql").exists()
        )

    def test_sync_returns_list(self):
        from admin_panel.services import sync_backup_records

        with patch("admin_panel.services.BACKUP_DIR", self.backup_dir):
            result = sync_backup_records()

        self.assertIsInstance(result, list)

    # ── delete_backup ─────────────────────────────────────────

    def test_delete_removes_file_and_db_record(self):
        from admin_panel.services import delete_backup
        from admin_panel.models import BackupRecord

        backup_file = self.backup_dir / "to_delete.sql"
        backup_file.write_text("-- dump --")
        BackupRecord.objects.create(filename="to_delete.sql", size_bytes=10)

        with patch("admin_panel.services.BACKUP_DIR", self.backup_dir):
            delete_backup("to_delete.sql", actor=self.admin)

        self.assertFalse(backup_file.exists())
        self.assertFalse(BackupRecord.objects.filter(filename="to_delete.sql").exists())

    def test_delete_creates_audit_log(self):
        from admin_panel.services import delete_backup
        from admin_panel.models import AuditLog, BackupRecord

        backup_file = self.backup_dir / "audit_del.sql"
        backup_file.write_text("-- dump --")
        BackupRecord.objects.create(filename="audit_del.sql", size_bytes=5)

        with patch("admin_panel.services.BACKUP_DIR", self.backup_dir):
            delete_backup("audit_del.sql", actor=self.admin)

        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.ActionType.BACKUP_DELETE,
                resource_str="audit_del.sql",
            ).exists()
        )

    def test_delete_nonexistent_file_does_not_raise(self):
        """Удаление несуществующего файла не должно падать."""
        from admin_panel.services import delete_backup

        with patch("admin_panel.services.BACKUP_DIR", self.backup_dir):
            # Файл не существует, но и записи в DB нет — должно пройти тихо
            delete_backup("ghost.sql")

    # ── restore_database_backup ───────────────────────────────

    @patch("admin_panel.services.subprocess.run")
    def test_restore_success(self, mock_run):
        from admin_panel.services import restore_database_backup

        backup_file = self.backup_dir / "restore_me.sql"
        backup_file.write_text("-- dump --")

        mock_run.return_value.returncode = 0

        with patch("admin_panel.services.BACKUP_DIR", self.backup_dir):
            restore_database_backup("restore_me.sql", actor=self.admin)

        mock_run.assert_called_once()

    @patch("admin_panel.services.subprocess.run")
    def test_restore_creates_audit_log(self, mock_run):
        from admin_panel.services import restore_database_backup
        from admin_panel.models import AuditLog

        backup_file = self.backup_dir / "restore_audit.sql"
        backup_file.write_text("-- dump --")
        mock_run.return_value.returncode = 0

        with patch("admin_panel.services.BACKUP_DIR", self.backup_dir):
            restore_database_backup("restore_audit.sql", actor=self.admin)

        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.ActionType.BACKUP_RESTORE,
                resource_str="restore_audit.sql",
            ).exists()
        )

    def test_restore_missing_file_raises(self):
        from admin_panel.services import restore_database_backup

        with patch("admin_panel.services.BACKUP_DIR", self.backup_dir):
            with self.assertRaises(FileNotFoundError):
                restore_database_backup("nonexistent.sql")

    @patch("admin_panel.services.subprocess.run")
    def test_restore_psql_failure_raises(self, mock_run):
        from admin_panel.services import restore_database_backup

        backup_file = self.backup_dir / "broken.sql"
        backup_file.write_text("-- broken dump --")
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "FATAL: role does not exist"

        with patch("admin_panel.services.BACKUP_DIR", self.backup_dir):
            with self.assertRaises(RuntimeError) as ctx:
                restore_database_backup("broken.sql")
        self.assertIn("psql", str(ctx.exception))
