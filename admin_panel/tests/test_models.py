"""
Тесты моделей admin_panel: AuditLog и BackupRecord.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from admin_panel.models import AuditLog, BackupRecord

User = get_user_model()


class TestAuditLogStr(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="audit_str_user",
            email="auditstr@test.ru",
            password="Pass1!ABCDEFGH",
        )

    def test_str_with_user(self):
        entry = AuditLog.objects.create(
            user=self.user,
            action=AuditLog.ActionType.CREATE,
            resource_type="User",
            resource_str="some_resource",
        )
        result = str(entry)
        self.assertIn("audit_str_user", result)
        self.assertIn("Создание", result)

    def test_str_without_user(self):
        entry = AuditLog.objects.create(
            user=None,
            action=AuditLog.ActionType.DELETE,
            resource_type="User",
            resource_str="orphan",
        )
        result = str(entry)
        self.assertIn("system", result)
        self.assertIn("Удаление", result)

    def test_str_contains_timestamp(self):
        entry = AuditLog.objects.create(
            user=self.user,
            action=AuditLog.ActionType.UPDATE,
            resource_type="User",
        )
        result = str(entry)
        # Дата в формате DD.MM.YYYY
        self.assertRegex(result, r"\d{2}\.\d{2}\.\d{4}")


class TestBackupRecordStrAndProperty(TestCase):

    def test_str_returns_filename(self):
        record = BackupRecord(filename="backup_20250101_120000.sql", size_bytes=1024)
        self.assertEqual(str(record), "backup_20250101_120000.sql")

    def test_size_human_bytes(self):
        record = BackupRecord(filename="f.sql", size_bytes=512)
        self.assertEqual(record.size_human, "512.0 Б")

    def test_size_human_kb(self):
        record = BackupRecord(filename="f.sql", size_bytes=2048)
        self.assertEqual(record.size_human, "2.0 КБ")

    def test_size_human_mb(self):
        record = BackupRecord(filename="f.sql", size_bytes=1024 * 1024 * 3)
        self.assertEqual(record.size_human, "3.0 МБ")

    def test_size_human_gb(self):
        record = BackupRecord(filename="f.sql", size_bytes=1024 ** 3 * 2)
        self.assertEqual(record.size_human, "2.0 ГБ")

    def test_size_human_tb(self):
        """Крайний случай — терабайты (строка 95 в models.py)."""
        record = BackupRecord(filename="f.sql", size_bytes=1024 ** 4 * 5)
        self.assertEqual(record.size_human, "5.0 ТБ")
