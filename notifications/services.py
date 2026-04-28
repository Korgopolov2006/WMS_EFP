"""
Сервисный слой уведомлений.

`notify(user, ...)` — единая точка создания уведомления.
Поддерживает дедупликацию: если есть **непрочитанное** уведомление с тем же
`dedup_key`, оно обновляется (новый title/body), вместо плодения дубликатов.

`broadcast_to_role(role, ...)` — рассылка всем активным пользователям с указанной ролью.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable

from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import Notification, NotificationKind, NotificationPriority

logger = logging.getLogger(__name__)
User = get_user_model()


def notify(
    user,
    *,
    title: str,
    body: str = "",
    kind: str = NotificationKind.INFO,
    priority: str = NotificationPriority.NORMAL,
    link: str = "",
    dedup_key: str = "",
) -> Notification | None:
    """
    Создать или обновить уведомление пользователя.
    Возвращает экземпляр Notification или None при ошибке.
    """
    if not user or not getattr(user, "pk", None):
        return None

    title = (title or "").strip()[:200]
    if not title:
        return None

    if dedup_key:
        existing = (
            Notification.objects
            .filter(user=user, dedup_key=dedup_key, is_read=False)
            .first()
        )
        if existing:
            existing.title = title
            existing.body = body or ""
            existing.kind = kind
            existing.priority = priority
            existing.link = link or ""
            existing.save(update_fields=["title", "body", "kind", "priority", "link"])
            return existing

    try:
        return Notification.objects.create(
            user=user,
            title=title,
            body=body or "",
            kind=kind,
            priority=priority,
            link=link or "",
            dedup_key=dedup_key or "",
        )
    except Exception:
        logger.exception("Не удалось создать уведомление")
        return None


def broadcast_to_role(role: str, **kwargs) -> int:
    """
    Создаёт уведомления для всех активных пользователей с указанной ролью.
    Возвращает количество созданных уведомлений.
    """
    qs = User.objects.filter(is_active=True, role=role)
    return _bulk_notify(qs, **kwargs)


def broadcast_to_admins(**kwargs) -> int:
    """Рассылка всем суперпользователям и пользователям с ролью ADMIN."""
    from accounts.constants import Roles
    qs = User.objects.filter(is_active=True).filter(
        models_or(is_superuser=True, role=Roles.ADMIN)
    )
    return _bulk_notify(qs, **kwargs)


def models_or(**kwargs):
    """Маленький хелпер: ИЛИ-фильтр по нескольким kwargs."""
    from django.db.models import Q
    q = Q()
    for k, v in kwargs.items():
        q |= Q(**{k: v})
    return q


def _bulk_notify(users: Iterable, **kwargs) -> int:
    """Создать уведомления для нескольких пользователей."""
    count = 0
    for u in users:
        if notify(u, **kwargs):
            count += 1
    return count


def mark_read(notification: Notification) -> None:
    if notification.is_read:
        return
    notification.is_read = True
    notification.read_at = timezone.now()
    notification.save(update_fields=["is_read", "read_at"])


def mark_all_read(user) -> int:
    """Помечает все непрочитанные уведомления пользователя прочитанными."""
    return Notification.objects.filter(user=user, is_read=False).update(
        is_read=True, read_at=timezone.now(),
    )


def unread_count(user) -> int:
    if not getattr(user, "is_authenticated", False):
        return 0
    return Notification.objects.filter(user=user, is_read=False).count()
