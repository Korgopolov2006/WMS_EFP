"""
Сигналы — автоматические уведомления для событий бизнес-логики.

Подключаются из NotificationsConfig.ready().
"""
from __future__ import annotations

import logging

from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.urls import reverse

from .models import NotificationKind, NotificationPriority
from .services import broadcast_to_role, notify

logger = logging.getLogger(__name__)
User = get_user_model()

LOW_STOCK_THRESHOLD = 5  # шт.


@receiver(post_save, sender="picking.Order", dispatch_uid="notify_new_order")
def on_order_saved(sender, instance, created, **kwargs):
    """Новый заказ → менеджеры/админы получают уведомление."""
    if not created:
        return
    try:
        from accounts.constants import Roles
        link = reverse("order_detail", args=[instance.pk]) if instance.pk else ""
        broadcast_to_role(
            Roles.SALES_MANAGER,
            title=f"Новый заказ: {instance.number}",
            body=f"Создан новый заказ от {getattr(instance, 'customer_name', '—') or '—'}.",
            kind=NotificationKind.INFO,
            priority=NotificationPriority.NORMAL,
            link=link,
            dedup_key=f"order-new-{instance.pk}",
        )
        broadcast_to_role(
            Roles.ADMIN,
            title=f"Новый заказ: {instance.number}",
            body=f"Заказ {instance.number} создан.",
            kind=NotificationKind.INFO,
            link=link,
            dedup_key=f"order-new-admin-{instance.pk}",
        )
    except Exception:
        logger.exception("on_order_saved failed")


@receiver(post_save, sender="inventory.Stock", dispatch_uid="notify_low_stock")
def on_stock_saved(sender, instance, created, **kwargs):
    """
    Низкий остаток (qty_available <= LOW_STOCK_THRESHOLD)
    → уведомление кладовщикам и админам, дедуп по SKU.
    """
    try:
        if instance.qty_available is None or instance.qty_available > LOW_STOCK_THRESHOLD:
            return
        from accounts.constants import Roles
        sku = instance.product.internal_sku if instance.product_id else "?"
        title = f"Низкий остаток: {sku}"
        body = (
            f"Доступно {instance.qty_available} шт "
            f"в {instance.storage_location.code if instance.storage_location_id else '—'}."
        )
        link = reverse("stock_detail", args=[instance.product_id]) if instance.product_id else ""
        kind = NotificationKind.DANGER if instance.qty_available <= 0 else NotificationKind.WARNING

        broadcast_to_role(
            Roles.STOREKEEPER,
            title=title, body=body, kind=kind,
            priority=NotificationPriority.HIGH if kind == NotificationKind.DANGER else NotificationPriority.NORMAL,
            link=link,
            dedup_key=f"low-stock-{instance.product_id}",
        )
        broadcast_to_role(
            Roles.ADMIN,
            title=title, body=body, kind=kind,
            priority=NotificationPriority.NORMAL,
            link=link,
            dedup_key=f"low-stock-adm-{instance.product_id}",
        )
    except Exception:
        logger.exception("on_stock_saved failed")


@receiver(post_save, sender="admin_panel.BackupRecord", dispatch_uid="notify_backup")
def on_backup_saved(sender, instance, created, **kwargs):
    """Резервная копия создана → уведомление автору / всем админам."""
    if not created:
        return
    try:
        from accounts.constants import Roles
        title = f"Резервная копия создана: {instance.filename}"
        body = f"Размер: {instance.size_human}. Тип: {'авто' if instance.is_auto else 'ручная'}."
        link = reverse("admin_panel:backup_list")

        if instance.created_by_id:
            notify(
                instance.created_by,
                title=title, body=body,
                kind=NotificationKind.SUCCESS, link=link,
                dedup_key=f"backup-{instance.pk}",
            )
        else:
            broadcast_to_role(
                Roles.ADMIN,
                title=title, body=body,
                kind=NotificationKind.SUCCESS, link=link,
                dedup_key=f"backup-{instance.pk}",
            )
    except Exception:
        logger.exception("on_backup_saved failed")


@receiver(post_save, sender=User, dispatch_uid="notify_new_user")
def on_user_created(sender, instance, created, **kwargs):
    """Регистрация нового пользователя → админам."""
    if not created:
        return
    try:
        from accounts.constants import Roles
        broadcast_to_role(
            Roles.ADMIN,
            title=f"Новый пользователь: {instance.username}",
            body=f"Email: {instance.email or '—'}. Роль: {instance.get_role_display()}.",
            kind=NotificationKind.INFO,
            link=reverse("admin_panel:user_detail", args=[instance.pk]),
            dedup_key=f"user-new-{instance.pk}",
        )
    except Exception:
        logger.exception("on_user_created failed")
