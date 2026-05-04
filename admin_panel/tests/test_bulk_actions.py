"""
Тесты массовых действий: products bulk, users bulk.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from admin_panel.models import AuditLog

User = get_user_model()


def _admin():
    return User.objects.create_superuser(
        username="bulk_admin", email="ba@t.ru", password="Pass1!ABCDEFGH",
    )


def _make_products(n=5):
    """Создаёт n товаров для тестов bulk."""
    from catalog.models import Brand, Category, Product
    brand, _ = Brand.objects.get_or_create(name="BulkTestBrand")
    category, _ = Category.objects.get_or_create(name="BulkTestCat")
    products = []
    for i in range(n):
        p, _ = Product.objects.get_or_create(
            internal_sku=f"BULK-T-{i}",
            defaults={
                "name": f"Bulk product {i}",
                "oem_number": f"BULK-OEM-{i}",
                "brand": brand,
                "category": category,
            },
        )
        products.append(p)
    return products, brand, category


# ─────────────────────────── Products ───────────────────────────

class TestProductBulk(TestCase):
    def setUp(self):
        self.admin = _admin()
        self.client.force_login(self.admin)
        self.products, self.brand, self.cat = _make_products(4)
        self.url = reverse("admin_panel:wms_product_bulk")

    def test_empty_ids_redirects(self):
        resp = self.client.post(self.url, {"action": "delete", "ids": ""})
        self.assertEqual(resp.status_code, 302)

    def test_unknown_action_rejected(self):
        ids = ",".join(str(p.pk) for p in self.products[:2])
        resp = self.client.post(self.url, {"action": "foo", "ids": ids})
        self.assertEqual(resp.status_code, 302)

    def test_bulk_delete(self):
        from catalog.models import Product
        ids_to_del = self.products[:2]
        ids_str = ",".join(str(p.pk) for p in ids_to_del)
        resp = self.client.post(self.url, {"action": "delete", "ids": ids_str})
        self.assertEqual(resp.status_code, 302)
        # Удалены
        for p in ids_to_del:
            self.assertFalse(Product.objects.filter(pk=p.pk).exists())
        # Остались
        for p in self.products[2:]:
            self.assertTrue(Product.objects.filter(pk=p.pk).exists())

    def test_bulk_set_category(self):
        from catalog.models import Category
        new_cat = Category.objects.create(name="BulkTestCat2")
        ids_str = ",".join(str(p.pk) for p in self.products)
        resp = self.client.post(self.url, {
            "action": "set_category",
            "ids": ids_str,
            "category": str(new_cat.pk),
        })
        self.assertEqual(resp.status_code, 302)
        for p in self.products:
            p.refresh_from_db()
            self.assertEqual(p.category_id, new_cat.pk)

    def test_bulk_set_category_invalid(self):
        ids_str = ",".join(str(p.pk) for p in self.products)
        resp = self.client.post(self.url, {
            "action": "set_category",
            "ids": ids_str,
            "category": "999999",
        })
        self.assertEqual(resp.status_code, 302)

    def test_bulk_set_brand(self):
        from catalog.models import Brand
        new_brand = Brand.objects.create(name="BulkTestBrand2")
        ids_str = ",".join(str(p.pk) for p in self.products)
        resp = self.client.post(self.url, {
            "action": "set_brand",
            "ids": ids_str,
            "brand": str(new_brand.pk),
        })
        self.assertEqual(resp.status_code, 302)
        for p in self.products:
            p.refresh_from_db()
            self.assertEqual(p.brand_id, new_brand.pk)

    def test_bulk_action_writes_audit(self):
        before = AuditLog.objects.count()
        ids_str = ",".join(str(p.pk) for p in self.products[:1])
        self.client.post(self.url, {"action": "delete", "ids": ids_str})
        self.assertGreater(AuditLog.objects.count(), before)


# ─────────────────────────── Users ───────────────────────────

class TestUserBulk(TestCase):
    def setUp(self):
        self.admin = _admin()
        self.client.force_login(self.admin)
        # 3 обычных пользователя
        self.u1 = User.objects.create_user(
            username="bulk_u1", email="u1@t.ru",
            password="Pass1!ABCDEFGH", role="STOREKEEPER",
        )
        self.u2 = User.objects.create_user(
            username="bulk_u2", email="u2@t.ru",
            password="Pass1!ABCDEFGH", role="STOREKEEPER",
        )
        self.u3 = User.objects.create_user(
            username="bulk_u3", email="u3@t.ru",
            password="Pass1!ABCDEFGH", role="ANALYST", is_active=False,
        )
        self.url = reverse("admin_panel:user_bulk")

    def _ids(self, *users):
        return ",".join(str(u.pk) for u in users)

    def test_block_active_users(self):
        resp = self.client.post(self.url, {
            "action": "block",
            "ids": self._ids(self.u1, self.u2),
            "reason": "Нарушение регламента",
        })
        self.assertEqual(resp.status_code, 302)
        self.u1.refresh_from_db()
        self.u2.refresh_from_db()
        self.assertFalse(self.u1.is_active)
        self.assertFalse(self.u2.is_active)

    def test_block_writes_audit_with_reason(self):
        before = AuditLog.objects.filter(
            action=AuditLog.ActionType.DEACTIVATE
        ).count()
        self.client.post(self.url, {
            "action": "block",
            "ids": self._ids(self.u1),
            "reason": "Test reason 123",
        })
        logs = AuditLog.objects.filter(action=AuditLog.ActionType.DEACTIVATE)
        self.assertEqual(logs.count(), before + 1)
        last = logs.order_by("-id").first()
        self.assertEqual(last.changes.get("reason"), "Test reason 123")

    def test_unblock_inactive_users(self):
        resp = self.client.post(self.url, {
            "action": "unblock",
            "ids": self._ids(self.u3),
        })
        self.assertEqual(resp.status_code, 302)
        self.u3.refresh_from_db()
        self.assertTrue(self.u3.is_active)

    def test_set_role(self):
        resp = self.client.post(self.url, {
            "action": "set_role",
            "ids": self._ids(self.u1, self.u2),
            "role": "LOADER",
        })
        self.assertEqual(resp.status_code, 302)
        self.u1.refresh_from_db()
        self.u2.refresh_from_db()
        self.assertEqual(self.u1.role, "LOADER")
        self.assertEqual(self.u2.role, "LOADER")

    def test_set_role_invalid(self):
        resp = self.client.post(self.url, {
            "action": "set_role",
            "ids": self._ids(self.u1),
            "role": "BOGUS_ROLE",
        })
        self.assertEqual(resp.status_code, 302)
        self.u1.refresh_from_db()
        self.assertEqual(self.u1.role, "STOREKEEPER")  # не изменилось

    def test_self_excluded_from_bulk(self):
        """Текущий админ не должен быть заблокирован, даже если попал в ids."""
        resp = self.client.post(self.url, {
            "action": "block",
            "ids": self._ids(self.admin, self.u1),
        })
        self.assertEqual(resp.status_code, 302)
        self.admin.refresh_from_db()
        self.u1.refresh_from_db()
        self.assertTrue(self.admin.is_active)
        self.assertFalse(self.u1.is_active)

    def test_block_creates_persistent_notification(self):
        from notifications.models import Notification
        before = Notification.objects.filter(user=self.u1).count()
        self.client.post(self.url, {
            "action": "block",
            "ids": self._ids(self.u1),
            "reason": "Тест",
        })
        after = Notification.objects.filter(user=self.u1).count()
        self.assertEqual(after, before + 1)
        n = Notification.objects.filter(user=self.u1).order_by("-id").first()
        self.assertIn("Тест", n.body)
        self.assertEqual(n.kind, "DANGER")
        # уведомление в БД — переживает рестарт сервера

    def test_set_role_creates_notification(self):
        from notifications.models import Notification
        before = Notification.objects.filter(user=self.u1).count()
        self.client.post(self.url, {
            "action": "set_role",
            "ids": self._ids(self.u1),
            "role": "ANALYST",
        })
        self.assertGreater(Notification.objects.filter(user=self.u1).count(), before)

    def test_empty_ids(self):
        resp = self.client.post(self.url, {"action": "block", "ids": ""})
        self.assertEqual(resp.status_code, 302)
