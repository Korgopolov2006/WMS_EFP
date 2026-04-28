"""
Тесты модели/сервиса/views/сигналов уведомлений.
"""
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, signals as django_signals
from django.urls import reverse

from notifications.models import Notification, NotificationKind
from notifications.services import (
    broadcast_to_role,
    mark_all_read,
    mark_read,
    notify,
    unread_count,
)

User = get_user_model()


class TestNotify(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="notif_user", email="n@test.ru", password="Pass1!ABCDEFGH",
        )

    def test_creates_notification(self):
        n = notify(self.user, title="Hi", body="body", kind=NotificationKind.SUCCESS)
        self.assertIsNotNone(n)
        self.assertEqual(n.kind, NotificationKind.SUCCESS)
        self.assertFalse(n.is_read)

    def test_empty_title_rejected(self):
        self.assertIsNone(notify(self.user, title=""))
        self.assertIsNone(notify(self.user, title="   "))

    def test_no_user_rejected(self):
        self.assertIsNone(notify(None, title="x"))

    def test_dedup_key_updates_existing(self):
        n1 = notify(self.user, title="v1", dedup_key="k1")
        n2 = notify(self.user, title="v2", body="new", dedup_key="k1")
        self.assertEqual(n1.pk, n2.pk)
        n2.refresh_from_db()
        self.assertEqual(n2.title, "v2")
        self.assertEqual(n2.body, "new")
        self.assertEqual(Notification.objects.filter(user=self.user, dedup_key="k1").count(), 1)

    def test_dedup_does_not_resurrect_read(self):
        n1 = notify(self.user, title="v1", dedup_key="k2")
        mark_read(n1)
        n2 = notify(self.user, title="v2", dedup_key="k2")
        self.assertNotEqual(n1.pk, n2.pk)


class TestUnreadCount(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="ucu", email="ucu@test.ru", password="Pass1!ABCDEFGH",
        )

    def test_unread_zero_initially(self):
        self.assertEqual(unread_count(self.user), 0)

    def test_unread_grows_and_resets(self):
        for i in range(3):
            notify(self.user, title=f"t{i}")
        self.assertEqual(unread_count(self.user), 3)
        mark_all_read(self.user)
        self.assertEqual(unread_count(self.user), 0)

    def test_anonymous_returns_zero(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertEqual(unread_count(AnonymousUser()), 0)


class TestBroadcast(TestCase):
    def test_broadcast_to_role(self):
        u1 = User.objects.create_user(username="r1", email="r1@t.ru",
                                      password="Pass1!ABCDEFGH", role="STOREKEEPER")
        u2 = User.objects.create_user(username="r2", email="r2@t.ru",
                                      password="Pass1!ABCDEFGH", role="STOREKEEPER")
        u3 = User.objects.create_user(username="r3", email="r3@t.ru",
                                      password="Pass1!ABCDEFGH", role="ANALYST")
        n = broadcast_to_role("STOREKEEPER", title="Stop")
        self.assertEqual(n, 2)
        self.assertEqual(unread_count(u1), 1)
        self.assertEqual(unread_count(u2), 1)
        self.assertEqual(unread_count(u3), 0)


class TestViews(TestCase):
    def setUp(self):
        self._tr = django_signals.template_rendered.receivers
        django_signals.template_rendered.receivers = []

        self.user = User.objects.create_user(
            username="nv", email="nv@t.ru", password="Pass1!ABCDEFGH",
        )
        self.factory = RequestFactory()
        notify(self.user, title="A", dedup_key="kA")
        notify(self.user, title="B", dedup_key="kB")

    def tearDown(self):
        django_signals.template_rendered.receivers = self._tr

    def test_unread_count_api(self):
        from notifications import views
        req = self.factory.get(reverse("notifications:unread_count"))
        req.user = self.user
        resp = views.unread_count_api(req)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'"count": 2', resp.content)

    def test_mark_one_read_view(self):
        from notifications import views
        n = Notification.objects.filter(user=self.user, is_read=False).first()
        req = self.factory.post(reverse("notifications:mark_read", args=[n.pk]))
        req.user = self.user
        resp = views.mark_one_read(req, pk=n.pk)
        self.assertIn(resp.status_code, (200, 302))
        n.refresh_from_db()
        self.assertTrue(n.is_read)

    def test_mark_all_view(self):
        from notifications import views
        req = self.factory.post(reverse("notifications:mark_all_read"))
        req.user = self.user
        resp = views.mark_all(req)
        self.assertIn(resp.status_code, (200, 302))
        self.assertEqual(unread_count(self.user), 0)


class TestSignals(TestCase):
    """Сигналы — низкий остаток должен создать уведомление кладовщику."""

    def test_low_stock_signal_triggers(self):
        sk = User.objects.create_user(
            username="sk_signal", email="sk@t.ru",
            password="Pass1!ABCDEFGH", role="STOREKEEPER",
        )
        before = Notification.objects.filter(user=sk).count()

        from catalog.models import Brand, Category, Product, StorageLocation, StorageZone, StorageZoneType
        from inventory.models import Stock

        zt, _ = StorageZoneType.objects.get_or_create(code="ZTSIG", defaults={"name": "ZTSIG"})
        zone, _ = StorageZone.objects.get_or_create(code="ZSIG", defaults={"name": "ZSIG", "zone_type": zt})
        loc, _ = StorageLocation.objects.get_or_create(zone=zone, code="SIG-A1")
        brand, _ = Brand.objects.get_or_create(name="SigBrand")
        cat, _ = Category.objects.get_or_create(name="SigCat")
        product, _ = Product.objects.get_or_create(
            internal_sku="SIG-LOW-1",
            defaults={"name": "Sig low", "oem_number": "SIG-OEM-1", "brand": brand, "category": cat},
        )

        Stock.objects.create(
            product=product, storage_location=loc,
            qty_available=0, qty_reserved=0,
        )

        after = Notification.objects.filter(user=sk).count()
        self.assertGreater(after, before)


class TestContextProcessor(TestCase):
    def test_anonymous_zero(self):
        from django.contrib.auth.models import AnonymousUser
        from notifications.context_processors import notifications as cp
        class Req:
            user = AnonymousUser()
        self.assertEqual(cp(Req())["notifications_unread"], 0)

    def test_authenticated_count(self):
        u = User.objects.create_user(username="cpu", email="c@t.ru", password="Pass1!ABCDEFGH")
        notify(u, title="x")
        from notifications.context_processors import notifications as cp
        class Req:
            user = u
        self.assertEqual(cp(Req())["notifications_unread"], 1)
