"""
Тесты для notifications/services.py — notify, broadcast, mark_read,
mark_all_read и сигналов.
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.constants import Roles
from catalog.models import (
    Branch,
    Brand,
    Category,
    Product,
    StorageLocation,
    StorageZone,
    StorageZoneType,
    Warehouse,
)
from inventory.models import Stock
from notifications.models import Notification, NotificationKind, NotificationPriority
from notifications.services import (
    _bulk_notify,
    broadcast_to_admins,
    broadcast_to_role,
    mark_all_read,
    mark_read,
    notify,
)
from picking.models import Order


User = get_user_model()


# ════════════════════════════════════════════════════════════════════
# notify
# ════════════════════════════════════════════════════════════════════
class NotifyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="n_user", email="nu@t.ru",
            password="Pass1!ABCDEFGH", role=Roles.STOREKEEPER,
        )

    def test_creates_notification(self):
        n = notify(self.user, title="Привет")
        self.assertIsNotNone(n)
        self.assertEqual(n.user, self.user)
        self.assertEqual(n.title, "Привет")

    def test_returns_none_for_invalid_user(self):
        self.assertIsNone(notify(None, title="X"))

    def test_returns_none_for_empty_title(self):
        self.assertIsNone(notify(self.user, title=""))

    def test_dedup_key_updates_existing_unread(self):
        n1 = notify(self.user, title="Старое", dedup_key="K1")
        n2 = notify(self.user, title="Новое", dedup_key="K1")
        # Один и тот же объект, обновлён title
        self.assertEqual(n1.pk, n2.pk)
        n1.refresh_from_db()
        self.assertEqual(n1.title, "Новое")

    def test_dedup_skips_read_notifications(self):
        n1 = notify(self.user, title="Read", dedup_key="K2")
        n1.is_read = True
        n1.save()
        # Второй раз — создаётся новое
        n2 = notify(self.user, title="Second", dedup_key="K2")
        self.assertNotEqual(n1.pk, n2.pk)

    def test_title_truncated_to_200(self):
        long_title = "x" * 300
        n = notify(self.user, title=long_title)
        self.assertEqual(len(n.title), 200)


# ════════════════════════════════════════════════════════════════════
# broadcast_to_role / broadcast_to_admins
# ════════════════════════════════════════════════════════════════════
class BroadcastTests(TestCase):
    def setUp(self):
        # 2 кладовщика, 1 админ, 1 неактивный — фильтруется
        self.stk1 = User.objects.create_user(
            username="stk1", email="s1@t.ru",
            password="Pass1!ABCDEFGH", role=Roles.STOREKEEPER,
        )
        self.stk2 = User.objects.create_user(
            username="stk2", email="s2@t.ru",
            password="Pass1!ABCDEFGH", role=Roles.STOREKEEPER,
        )
        self.inactive = User.objects.create_user(
            username="inact", email="in@t.ru",
            password="Pass1!ABCDEFGH", role=Roles.STOREKEEPER,
            is_active=False,
        )
        self.admin = User.objects.create_user(
            username="brc_admin", email="brc@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.ADMIN, is_superuser=True,
        )

    def test_broadcast_to_role_creates_for_active_only(self):
        count = broadcast_to_role(Roles.STOREKEEPER, title="Внимание")
        self.assertEqual(count, 2)
        # неактивный пропущен
        self.assertFalse(Notification.objects.filter(user=self.inactive).exists())

    def test_broadcast_to_admins_includes_superuser(self):
        count = broadcast_to_admins(title="Админам")
        self.assertGreaterEqual(count, 1)
        self.assertTrue(Notification.objects.filter(user=self.admin).exists())


# ════════════════════════════════════════════════════════════════════
# mark_read / mark_all_read
# ════════════════════════════════════════════════════════════════════
class MarkReadTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="m_user", email="mu@t.ru",
            password="Pass1!ABCDEFGH", role=Roles.STOREKEEPER,
        )

    def test_mark_read_sets_read_at(self):
        n = notify(self.user, title="t")
        self.assertFalse(n.is_read)
        mark_read(n)
        n.refresh_from_db()
        self.assertTrue(n.is_read)
        self.assertIsNotNone(n.read_at)

    def test_mark_read_idempotent(self):
        n = notify(self.user, title="t")
        n.is_read = True
        n.read_at = timezone.now()
        n.save()
        # Повторный вызов не падает и не меняет ничего
        mark_read(n)
        n.refresh_from_db()
        self.assertTrue(n.is_read)

    def test_mark_all_read_returns_count(self):
        for i in range(3):
            notify(self.user, title=f"t{i}")
        marked = mark_all_read(self.user)
        self.assertEqual(marked, 3)
        self.assertEqual(
            Notification.objects.filter(user=self.user, is_read=False).count(),
            0,
        )


# ════════════════════════════════════════════════════════════════════
# Сигналы post_save
# ════════════════════════════════════════════════════════════════════
class SignalsTests(TestCase):
    def setUp(self):
        self.sales = User.objects.create_user(
            username="sig_sales", email="ss@t.ru",
            password="Pass1!ABCDEFGH", role=Roles.SALES_MANAGER,
        )
        self.stk = User.objects.create_user(
            username="sig_stk", email="sgk@t.ru",
            password="Pass1!ABCDEFGH", role=Roles.STOREKEEPER,
        )
        self.admin = User.objects.create_user(
            username="sig_admin", email="sa@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.ADMIN, is_superuser=True,
        )

    def test_new_order_creates_notification_for_sales(self):
        order = Order.objects.create(
            number=Order.generate_next_number(),
            customer_name="Иван", customer_phone="+79991234567",
            created_by=self.admin,
        )
        # Сигнал автоматически создаст уведомление для sales/admin
        self.assertTrue(
            Notification.objects.filter(user=self.sales).exists()
        )

    def test_low_stock_creates_warning(self):
        # Готовим склад
        branch = Branch.objects.create(code="BR1", name="X")
        warehouse = Warehouse.objects.create(branch=branch, code="WH1", name="WH1")
        zt, _ = StorageZoneType.objects.get_or_create(code="CELL", defaults={"name": "Ячейка"})
        zone = StorageZone.objects.create(
            warehouse=warehouse, code="Z1", name="Z1", zone_type=zt,
        )
        loc = StorageLocation.objects.create(zone=zone, code="L1", name="L1")
        brand = Brand.objects.create(name="X")
        cat = Category.objects.create(name="Y")
        product = Product.objects.create(
            internal_sku="LOW-STOCK", name="X",
            oem_number="OEM", brand=brand, category=cat,
        )
        # Создаём остаток с qty <= LOW_STOCK_THRESHOLD = 5
        Stock.objects.create(
            product=product, storage_location=loc, qty_available=Decimal("2"),
        )
        # Уведомление пришло кладовщику
        warnings = Notification.objects.filter(
            user=self.stk, dedup_key=f"low-stock-{product.id}",
        )
        self.assertTrue(warnings.exists())

    def test_high_stock_does_not_trigger_warning(self):
        branch = Branch.objects.create(code="BR2", name="X")
        warehouse = Warehouse.objects.create(branch=branch, code="WH2", name="WH2")
        zt, _ = StorageZoneType.objects.get_or_create(code="CELL", defaults={"name": "Ячейка"})
        zone = StorageZone.objects.create(
            warehouse=warehouse, code="Z2", name="Z2", zone_type=zt,
        )
        loc = StorageLocation.objects.create(zone=zone, code="L2", name="L2")
        brand = Brand.objects.create(name="Y")
        cat = Category.objects.create(name="Z")
        product = Product.objects.create(
            internal_sku="HIGH-STOCK", name="X",
            oem_number="OEM-H", brand=brand, category=cat,
        )
        # Большой остаток — не должно быть уведомлений low-stock
        Stock.objects.create(
            product=product, storage_location=loc, qty_available=Decimal("100"),
        )
        self.assertFalse(
            Notification.objects.filter(dedup_key=f"low-stock-{product.id}").exists()
        )
