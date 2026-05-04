"""
Сервисный слой административной панели WMS.
Бизнес-логика: генерация паролей, создание пользователей, email, бэкапы, аудит.
"""
from __future__ import annotations

import glob
import logging
import os
import secrets
import shutil
import string
import subprocess
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING


from django.conf import settings
from django.core.mail import send_mail
from django.db import connections
from django.utils.text import get_valid_filename
from django.utils import timezone

if TYPE_CHECKING:
    from accounts.models import User
    from .models import AuditLog, BackupRecord

logger = logging.getLogger(__name__)

# ---------- Константы ----------

SPECIAL_CHARS = "!@#$%^&*()-_=+[]{}|;:,.<>?"
PASSWORD_LENGTH = 16
BACKUP_DIR: Path = Path(getattr(settings, "BACKUP_DIR", Path(settings.BASE_DIR) / "backups"))


# ---------- Пароли ----------

def generate_secure_password(length: int = PASSWORD_LENGTH) -> str:
    """
    Генерация криптографически безопасного пароля.
    Гарантирует наличие: заглавной, строчной, цифры, спецсимвола.
    """
    # Гарантированный минимум каждого класса
    required = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice(SPECIAL_CHARS),
    ]
    # Заполнение оставшихся символов
    alphabet = string.ascii_letters + string.digits + SPECIAL_CHARS
    rest = [secrets.choice(alphabet) for _ in range(length - len(required))]

    # Перемешиваем системным PRNG
    chars = required + rest
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def validate_password_complexity(password: str) -> tuple[bool, list[str]]:
    """
    Проверка сложности пароля.
    Возвращает (is_valid, list_of_errors).
    """
    errors: list[str] = []
    if len(password) < PASSWORD_LENGTH:
        errors.append(f"Минимальная длина — {PASSWORD_LENGTH} символов.")
    if not any(c.isupper() for c in password):
        errors.append("Нет заглавной буквы.")
    if not any(c.islower() for c in password):
        errors.append("Нет строчной буквы.")
    if not any(c.isdigit() for c in password):
        errors.append("Нет цифры.")
    if not any(c in SPECIAL_CHARS for c in password):
        errors.append("Нет специального символа.")
    return (len(errors) == 0, errors)


# ---------- Управление пользователями ----------

def create_user_with_credentials(
    admin_user,
    cleaned_data: dict,
    request=None,
) -> tuple[User, str]:
    """
    Создаёт пользователя с автоматически сгенерированным паролем
    и отправляет приветственное письмо.

    Returns:
        (user, raw_password)
    """
    from accounts.models import User
    from .models import AuditLog

    raw_password = generate_secure_password()

    user = User(
        username=cleaned_data["username"],
        email=cleaned_data["email"],
        first_name=cleaned_data.get("first_name", ""),
        last_name=cleaned_data.get("last_name", ""),
        role=cleaned_data["role"],
        is_active=True,
    )
    user.set_password(raw_password)
    user.save()

    if cleaned_data.get("branches"):
        user.branches.set(cleaned_data["branches"])

    log_action(
        actor=admin_user,
        action=AuditLog.ActionType.CREATE,
        resource_type="User",
        resource_id=str(user.pk),
        resource_str=f"{user.username} ({user.get_role_display()})",
        changes={
            "username": user.username,
            "email": user.email,
            "role": user.role,
        },
        request=request,
    )

    try:
        send_welcome_email(user, raw_password, request)
    except Exception:
        pass  # не прерываем создание при ошибке почты

    return user, raw_password


def reset_user_password(admin_user, target_user, request=None) -> str:
    """
    Генерирует новый пароль для пользователя и отправляет его на email.

    Returns:
        raw_password
    """
    from .models import AuditLog

    raw_password = generate_secure_password()
    target_user.set_password(raw_password)
    target_user.save(update_fields=["password"])

    log_action(
        actor=admin_user,
        action=AuditLog.ActionType.PASSWORD_RESET,
        resource_type="User",
        resource_id=str(target_user.pk),
        resource_str=target_user.username,
        request=request,
    )

    try:
        send_welcome_email(target_user, raw_password, request)
    except Exception:
        pass

    return raw_password


def send_welcome_email(user: User, raw_password: str, request=None) -> None:
    """Отправка письма с учётными данными новому пользователю."""
    site_url = getattr(settings, "SITE_URL", "http://localhost:8000")
    if request:
        site_url = request.build_absolute_uri("/").rstrip("/")

    display_name = user.get_full_name() or user.username
    subject = "Ваши данные для входа в WMS ЕФП-ПАРТС"

    text_body = (
        f"Здравствуйте, {display_name}!\n\n"
        "Для вас создана учётная запись в системе управления складом WMS ЕФП-ПАРТС.\n\n"
        f"  Логин: {user.username}\n"
        f"  Пароль: {raw_password}\n"
        f"  Роль: {user.get_role_display()}\n\n"
        f"Для входа перейдите по ссылке: {site_url}/accounts/login/\n\n"
        "Пожалуйста, смените пароль после первого входа.\n\n"
        "С уважением,\nАдминистрация WMS ЕФП-ПАРТС"
    )

    html_body = f"""<!DOCTYPE html>
<html>
<body style="font-family:system-ui,sans-serif;max-width:480px;margin:0 auto;color:#18181b;">
  <h2 style="color:#2563eb;">Добро пожаловать в WMS ЕФП-ПАРТС!</h2>
  <p>Здравствуйте, <strong>{display_name}</strong>!</p>
  <p>Для вас создана учётная запись.</p>
  <table style="border-collapse:collapse;margin:16px 0;">
    <tr><td style="padding:4px 12px 4px 0;color:#71717a;">Логин:</td>
        <td><code style="background:#f4f4f5;padding:2px 6px;border-radius:4px;">{user.username}</code></td></tr>
    <tr><td style="padding:4px 12px 4px 0;color:#71717a;">Пароль:</td>
        <td><code style="background:#f4f4f5;padding:2px 6px;border-radius:4px;">{raw_password}</code></td></tr>
    <tr><td style="padding:4px 12px 4px 0;color:#71717a;">Роль:</td>
        <td>{user.get_role_display()}</td></tr>
  </table>
  <a href="{site_url}/accounts/login/"
     style="display:inline-block;background:#2563eb;color:#fff;padding:10px 20px;
            border-radius:6px;text-decoration:none;font-weight:500;">
    Войти в систему
  </a>
  <p style="margin-top:16px;color:#dc2626;font-size:13px;">
    ⚠ Пожалуйста, смените пароль после первого входа!
  </p>
</body>
</html>"""

    send_mail(
        subject=subject,
        message=text_body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@efp-parts.ru"),
        recipient_list=[user.email],
        html_message=html_body,
        fail_silently=False,
    )


# ---------- Журнал аудита ----------

def log_action(
    actor,
    action: str,
    resource_type: str = "",
    resource_id: str = "",
    resource_str: str = "",
    changes: dict | None = None,
    request=None,
) -> AuditLog:
    """Записывает действие в журнал аудита."""
    from .models import AuditLog

    ip_address = None
    user_agent = ""
    if request:
        xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
        ip_address = xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR")
        user_agent = request.META.get("HTTP_USER_AGENT", "")[:512]

    return AuditLog.objects.create(
        user=actor,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        resource_str=resource_str,
        changes=changes,
        ip_address=ip_address,
        user_agent=user_agent,
    )


# ---------- Резервные копии ----------

def _get_backup_dir() -> Path:
    path = BACKUP_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_backup_path(filename: str) -> Path:
    """Защита от path traversal — файл должен быть внутри backup_dir."""
    backup_dir = _get_backup_dir()
    candidate = (backup_dir / filename).resolve()
    if not str(candidate).startswith(str(backup_dir.resolve())):
        raise ValueError("Недопустимое имя файла резервной копии.")
    return candidate


# Расширения, которые считаются файлами резервных копий
_BACKUP_EXTS = (".sql", ".sqlite3", ".db")


def _is_sqlite(db: dict) -> bool:
    return "sqlite" in str(db.get("ENGINE", "")).lower()


def _find_pg_executable(name: str) -> str | None:
    """
    Ищет pg_dump.exe / psql.exe / pg_restore.exe.
    Порядок: явная настройка PG_BIN_DIR / env PGBIN → PATH → типичные пути Windows.
    Возвращает абсолютный путь либо None.
    """
    exe = name + (".exe" if os.name == "nt" else "")

    # 1) явная настройка в Django settings
    pg_bin = getattr(settings, "PG_BIN_DIR", None) or os.environ.get("PGBIN")
    if pg_bin:
        candidate = Path(pg_bin) / exe
        if candidate.is_file():
            return str(candidate)

    # 2) PATH
    found = shutil.which(name) or shutil.which(exe)
    if found:
        return found

    # 3) Типичные пути установки PostgreSQL на Windows
    if os.name == "nt":
        patterns = [
            r"C:\Program Files\PostgreSQL\*\bin",
            r"C:\Program Files (x86)\PostgreSQL\*\bin",
        ]
        for pattern in patterns:
            for bin_dir in sorted(glob.glob(pattern), reverse=True):  # новейшая версия первой
                candidate = Path(bin_dir) / exe
                if candidate.is_file():
                    return str(candidate)
    return None


def _require_pg_executable(name: str) -> str:
    path = _find_pg_executable(name)
    if not path:
        raise RuntimeError(
            f"Не найден исполняемый файл «{name}». "
            f"Установите PostgreSQL и добавьте папку bin в PATH "
            f"(например, C:\\Program Files\\PostgreSQL\\<версия>\\bin) "
            f"или задайте переменную PG_BIN_DIR в settings."
        )
    return path


def create_database_backup(
    created_by=None,
    notes: str = "",
    is_auto: bool = False,
) -> BackupRecord:
    """
    Создаёт резервную копию активной БД.
    PostgreSQL — через pg_dump; SQLite — копированием файла БД.
    """
    from .models import AuditLog, BackupRecord

    db = settings.DATABASES["default"]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    if _is_sqlite(db):
        src = Path(db["NAME"])
        if not src.is_file():
            raise FileNotFoundError(f"Файл БД SQLite не найден: {src}")
        filename = f"backup_{ts}.sqlite3"
        backup_path = _get_backup_dir() / filename
        try:
            shutil.copy2(src, backup_path)
        except OSError as exc:
            logger.exception("Ошибка копирования файла SQLite")
            raise RuntimeError(f"Не удалось скопировать БД SQLite: {exc}") from exc
    else:
        filename = f"backup_{ts}.sql"
        backup_path = _get_backup_dir() / filename
        pg_dump = _require_pg_executable("pg_dump")

        env = os.environ.copy()
        password = db.get("PASSWORD", "")
        if password:
            env["PGPASSWORD"] = str(password)

        cmd = [
            pg_dump,
            "-h", str(db.get("HOST", "localhost")),
            "-p", str(db.get("PORT", "5432")),
            "-U", str(db.get("USER", "postgres")),
            "-d", str(db.get("NAME", "")),
            "--no-password",
            "--format=plain",
            "--encoding=UTF8",
            # --clean + --if-exists: восстановление сначала дропает существующие таблицы,
            # благодаря этому psql -f не падает на «duplicate key value violates pkey».
            "--clean",
            "--if-exists",
            "-f", str(backup_path),
        ]
        try:
            result = subprocess.run(
                cmd, env=env, capture_output=True, text=True, timeout=300
            )
        except FileNotFoundError as exc:
            logger.exception("pg_dump не запустился")
            raise RuntimeError(
                f"Не удалось запустить pg_dump: {exc}. Проверьте установку PostgreSQL."
            ) from exc
        if result.returncode != 0:
            logger.error("pg_dump returncode=%s stderr=%s", result.returncode, result.stderr)
            raise RuntimeError(f"pg_dump завершился с ошибкой: {result.stderr[:500]}")

    size = backup_path.stat().st_size if backup_path.exists() else 0
    # Защита от расхождения PK-sequence (часто после restore старого backup-а):
    # синхронизируем sequence перед INSERT, чтобы не получить duplicate key.
    _sync_pk_sequence(BackupRecord)
    record = BackupRecord.objects.create(
        filename=filename,
        size_bytes=size,
        created_by=created_by,
        notes=notes,
        is_auto=is_auto,
    )
    logger.info("Создана резервная копия %s (%s байт)", filename, size)

    if created_by:
        log_action(
            actor=created_by,
            action=AuditLog.ActionType.BACKUP_CREATE,
            resource_type="BackupRecord",
            resource_id=str(record.pk),
            resource_str=filename,
        )

    return record


def upload_backup_file(uploaded_file, *, actor=None, notes: str = "") -> BackupRecord:
    """Сохраняет загруженный пользователем файл backup-а в BACKUP_DIR."""
    from .models import AuditLog, BackupRecord

    original_name = get_valid_filename(Path(uploaded_file.name or "backup.sql").name)
    suffix = Path(original_name).suffix.lower()
    if suffix not in _BACKUP_EXTS:
        raise ValueError("Недопустимый формат файла резервной копии.")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = Path(original_name).stem[:80] or "uploaded"
    filename = f"backup_uploaded_{ts}_{base_name}{suffix}"
    path = _safe_backup_path(filename)

    index = 1
    while path.exists() or BackupRecord.objects.filter(filename=filename).exists():
        filename = f"backup_uploaded_{ts}_{base_name}_{index}{suffix}"
        path = _safe_backup_path(filename)
        index += 1

    with path.open("wb") as destination:
        for chunk in uploaded_file.chunks():
            destination.write(chunk)

    record = BackupRecord.objects.create(
        filename=filename,
        size_bytes=path.stat().st_size,
        created_by=actor,
        notes=notes.strip(),
        is_auto=False,
    )

    if actor:
        log_action(
            actor=actor,
            action=AuditLog.ActionType.BACKUP_CREATE,
            resource_type="BackupRecord",
            resource_id=str(record.pk),
            resource_str=filename,
        )

    return record


def sync_backup_records() -> list[BackupRecord]:
    """
    Синхронизирует записи BackupRecord с файловой системой.
    Учитывает форматы PG (.sql) и SQLite (.sqlite3, .db).
    """
    from .models import BackupRecord

    backup_dir = _get_backup_dir()
    existing_filenames = set(BackupRecord.objects.values_list("filename", flat=True))

    files: list[Path] = []
    for ext in _BACKUP_EXTS:
        files.extend(backup_dir.glob(f"backup_*{ext}"))
    files.sort(key=lambda p: p.name, reverse=True)

    for path in files:
        if path.name not in existing_filenames:
            BackupRecord.objects.get_or_create(
                filename=path.name,
                defaults={"size_bytes": path.stat().st_size},
            )

    for record in BackupRecord.objects.all():
        if not (backup_dir / record.filename).exists():
            record.delete()

    return list(BackupRecord.objects.all().order_by("-created_at"))


def delete_backup(filename: str, actor=None) -> None:
    """Удаляет файл резервной копии и запись в БД."""
    from .models import AuditLog, BackupRecord

    path = _safe_backup_path(filename)
    if path.exists():
        try:
            path.unlink()
        except OSError as exc:
            logger.exception("Не удалось удалить файл backup")
            raise RuntimeError(f"Не удалось удалить файл: {exc}") from exc

    BackupRecord.objects.filter(filename=filename).delete()
    logger.info("Удалена резервная копия %s", filename)

    if actor:
        log_action(
            actor=actor,
            action=AuditLog.ActionType.BACKUP_DELETE,
            resource_type="BackupRecord",
            resource_str=filename,
        )


def _sync_pk_sequence(model_cls) -> None:
    """
    Синхронизирует PostgreSQL-sequence для PK с реальным MAX(id).
    Решает проблему `duplicate key value violates pkey` после restore
    старого backup'а: в БД есть строки с id=N, но sequence был перезаписан
    в backup-е более старым значением.

    На SQLite — no-op (там нет sequences в этом смысле).
    """
    db_engine = settings.DATABASES["default"].get("ENGINE", "")
    if "postgresql" not in db_engine.lower():
        return
    table = model_cls._meta.db_table
    pk_col = model_cls._meta.pk.column
    try:
        with connections["default"].cursor() as cur:
            cur.execute(
                "SELECT setval(pg_get_serial_sequence(%s, %s), "
                "COALESCE((SELECT MAX(" + pk_col + ") FROM " + table + "), 0) + 1, false)",
                [table, pk_col],
            )
    except Exception:
        logger.exception("Не удалось синхронизировать sequence для %s", table)


_PG_WIPE_SQL = """
DO $$
DECLARE r RECORD;
BEGIN
    FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname='public') LOOP
        EXECUTE 'TRUNCATE TABLE public.' || quote_ident(r.tablename) || ' RESTART IDENTITY CASCADE';
    END LOOP;
END $$;
"""

# Синхронизация всех sequences с реальным MAX(id) — выполняется после restore.
# Решает рассогласование, когда backup без --clean содержит INSERT'ы с явными id,
# но не сбрасывает sequences. Применяется ко всем serial-колонкам схемы public.
_PG_RESYNC_SEQUENCES_SQL = """
DO $$
DECLARE
    s RECORD;
    max_val BIGINT;
BEGIN
    FOR s IN (
        SELECT n.nspname AS schema_name,
               c.relname AS seq_name,
               t.relname AS table_name,
               a.attname AS column_name
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_depend d ON d.objid = c.oid AND d.deptype = 'a'
        JOIN pg_class t ON t.oid = d.refobjid
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = d.refobjsubid
        WHERE c.relkind = 'S' AND n.nspname = 'public'
    ) LOOP
        EXECUTE format('SELECT COALESCE(MAX(%I), 0) FROM %I.%I',
                       s.column_name, s.schema_name, s.table_name) INTO max_val;
        EXECUTE format('SELECT setval(%L, %s, false)',
                       quote_ident(s.schema_name) || '.' || quote_ident(s.seq_name),
                       max_val + 1);
    END LOOP;
END $$;
"""


def restore_database_backup(filename: str, actor=None, wipe_first: bool = False) -> None:
    """
    Восстанавливает БД из резервной копии.

    Args:
        filename:    имя файла backup в BACKUP_DIR
        actor:       пользователь (для аудита)
        wipe_first:  для PostgreSQL — выполнить TRUNCATE по всем public-таблицам
                     ДО применения SQL. Нужно для старых backup'ов, сделанных
                     без `--clean`, иначе psql падает на дублях PK.
    """
    from .models import AuditLog

    path = _safe_backup_path(filename)
    if not path.exists():
        raise FileNotFoundError(f"Файл резервной копии не найден: {filename}")

    db = settings.DATABASES["default"]

    if _is_sqlite(db):
        target = Path(db["NAME"])
        # Закрываем все Django-коннекты, иначе Windows держит файл открытым
        connections.close_all()
        try:
            shutil.copy2(path, target)
        except OSError as exc:
            logger.exception("Ошибка восстановления SQLite")
            raise RuntimeError(f"Не удалось заменить файл БД: {exc}") from exc
    else:
        psql = _require_pg_executable("psql")

        env = os.environ.copy()
        password = db.get("PASSWORD", "")
        if password:
            env["PGPASSWORD"] = str(password)

        psql_base = [
            psql,
            "-h", str(db.get("HOST", "localhost")),
            "-p", str(db.get("PORT", "5432")),
            "-U", str(db.get("USER", "postgres")),
            "-d", str(db.get("NAME", "")),
            "--no-password",
        ]

        # Шаг 1: при необходимости очищаем БД (TRUNCATE всех public-таблиц)
        if wipe_first:
            try:
                wipe_result = subprocess.run(
                    psql_base + ["-v", "ON_ERROR_STOP=1", "-c", _PG_WIPE_SQL],
                    env=env, capture_output=True, text=True, timeout=120,
                )
            except FileNotFoundError as exc:
                logger.exception("psql (wipe) не запустился")
                raise RuntimeError(
                    f"Не удалось запустить psql: {exc}. Проверьте установку PostgreSQL."
                ) from exc
            if wipe_result.returncode != 0:
                logger.error(
                    "psql wipe returncode=%s stderr=%s",
                    wipe_result.returncode, wipe_result.stderr,
                )
                raise RuntimeError(
                    f"Не удалось очистить БД перед восстановлением: "
                    f"{wipe_result.stderr[:500]}"
                )

        # Шаг 2: применяем SQL backup-а
        try:
            result = subprocess.run(
                psql_base + ["-f", str(path)],
                env=env, capture_output=True, text=True, timeout=600,
            )
        except FileNotFoundError as exc:
            logger.exception("psql не запустился")
            raise RuntimeError(
                f"Не удалось запустить psql: {exc}. Проверьте установку PostgreSQL."
            ) from exc
        if result.returncode != 0:
            logger.error("psql returncode=%s stderr=%s", result.returncode, result.stderr)
            raise RuntimeError(f"psql завершился с ошибкой: {result.stderr[:500]}")

        # Шаг 3: синхронизируем все sequences с MAX(id), чтобы последующие INSERT'ы
        # (например, новые backup-ы) не падали с duplicate key.
        try:
            subprocess.run(
                psql_base + ["-c", _PG_RESYNC_SEQUENCES_SQL],
                env=env, capture_output=True, text=True, timeout=60,
            )
        except Exception:
            logger.exception("Не удалось синхронизировать sequences после restore")

    logger.info("Восстановлена резервная копия %s", filename)

    if actor:
        log_action(
            actor=actor,
            action=AuditLog.ActionType.BACKUP_RESTORE,
            resource_type="BackupRecord",
            resource_str=filename,
        )


# ---------- Статистика для дашборда ----------

def get_admin_dashboard_stats() -> dict:
    """Сводная статистика для дашборда администратора."""
    from django.contrib.auth import get_user_model
    from tasks.models import Task, TaskStatus
    from receiving.models import Receiving, ReceivingStatus
    from picking.models import Order, OrderStatus
    from inventory.models import Stock
    from .models import AuditLog

    User = get_user_model()

    today = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)

    return {
        # Пользователи
        "total_users": User.objects.count(),
        "active_users": User.objects.filter(is_active=True).count(),
        "new_users_today": User.objects.filter(date_joined__gte=today).count(),
        # Задачи
        "pending_tasks": Task.objects.filter(status=TaskStatus.PENDING).count(),
        "in_progress_tasks": Task.objects.filter(status=TaskStatus.IN_PROGRESS).count(),
        "completed_today": Task.objects.filter(
            status=TaskStatus.COMPLETED, completed_at__gte=today
        ).count(),
        # Заказы
        "open_orders": Order.objects.exclude(status=OrderStatus.SHIPPED).exclude(
            status=OrderStatus.CANCELLED
        ).count(),
        "shipped_today": Order.objects.filter(
            status=OrderStatus.SHIPPED, updated_at__gte=today
        ).count(),
        # Остатки
        "total_sku": Stock.objects.values("product_id").distinct().count(),
        "low_stock_sku": Stock.objects.filter(qty_available__lte=0).count(),
        # Аудит
        "audit_today": AuditLog.objects.filter(timestamp__gte=today).count(),
        # Приёмка
        "receiving_draft": Receiving.objects.filter(
            status=ReceivingStatus.DRAFT
        ).count(),
    }
