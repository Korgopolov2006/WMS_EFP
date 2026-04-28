from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AuditLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(
                    choices=[
                        ("LOGIN", "Вход в систему"),
                        ("LOGOUT", "Выход из системы"),
                        ("CREATE", "Создание"),
                        ("UPDATE", "Обновление"),
                        ("DELETE", "Удаление"),
                        ("ACTIVATE", "Активация"),
                        ("DEACTIVATE", "Деактивация"),
                        ("BACKUP_CREATE", "Создание резервной копии"),
                        ("BACKUP_RESTORE", "Восстановление из резервной копии"),
                        ("BACKUP_DELETE", "Удаление резервной копии"),
                        ("PASSWORD_RESET", "Сброс пароля"),
                        ("VIEW", "Просмотр"),
                    ],
                    db_index=True, max_length=32, verbose_name="Действие",
                )),
                ("resource_type", models.CharField(blank=True, max_length=64, verbose_name="Тип ресурса")),
                ("resource_id", models.CharField(blank=True, max_length=64, verbose_name="ID ресурса")),
                ("resource_str", models.CharField(blank=True, max_length=255, verbose_name="Ресурс (текст)")),
                ("changes", models.JSONField(blank=True, null=True, verbose_name="Изменения")),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True, unpack_ipv4=True, verbose_name="IP адрес")),
                ("user_agent", models.CharField(blank=True, max_length=512, verbose_name="User-Agent")),
                ("timestamp", models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Дата и время")),
                ("user", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="audit_logs",
                    to=settings.AUTH_USER_MODEL,
                    verbose_name="Пользователь",
                )),
            ],
            options={"verbose_name": "Запись аудита", "verbose_name_plural": "Журнал аудита", "ordering": ["-timestamp"]},
        ),
        migrations.CreateModel(
            name="BackupRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("filename", models.CharField(max_length=255, unique=True, verbose_name="Имя файла")),
                ("size_bytes", models.BigIntegerField(default=0, verbose_name="Размер (байт)")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создано")),
                ("notes", models.TextField(blank=True, verbose_name="Заметки")),
                ("is_auto", models.BooleanField(default=False, verbose_name="Автоматический")),
                ("created_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="backups",
                    to=settings.AUTH_USER_MODEL,
                    verbose_name="Создал",
                )),
            ],
            options={"verbose_name": "Резервная копия", "verbose_name_plural": "Резервные копии", "ordering": ["-created_at"]},
        ),
    ]
