"""
Тесты модели/сервиса/представления журнала движения товара.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, signals
from django.urls import reverse

from inventory.views import movement_list

from catalog.models import (
    Brand,
    Category,
    Product,
    StorageLocation,
    StorageZone,
    StorageZoneType,
)
from inventory.models import (
    MovementStatus,
    MovementType,
)
from inventory.services import record_movement

User = get_user_model()


def _build_fixtures():
    zt, _ = StorageZoneType.objects.get_or_create(
        code="TST-MOV", defaults={"name": "TST-MOV"}
    )
    zone, _ = StorageZone.objects.get_or_create(
        code="ZMOV", defaults={"name": "ZMOV", "zone_type": zt},
    )
    loc1, _ = StorageLocation.objects.get_or_create(zone=zone, code="MOV-A01")
    loc2, _ = StorageLocation.objects.get_or_create(zone=zone, code="MOV-A02")
    brand, _ = Brand.objects.get_or_create(name="MovTestBrand")
    category, _ = Category.objects.get_or_create(name="MovTestCategory")
    product, _ = Product.objects.get_or_create(
        internal_sku="MOV-TEST-1",
        defaults={
            "name": "Mov test",
            "oem_number": "MOV-OEM-TEST-1",
            "brand": brand,
            "category": category,
        },
    )
    return product, loc1, loc2


class TestRecordMovement(TestCase):
    def setUp(self):
        self.product, self.loc1, self.loc2 = _build_fixtures()

    def test_creates_movement(self):
        m = record_movement(
            movement_type=MovementType.RECEIPT,
            product=self.product,
            quantity=Decimal("10"),
            to_location=self.loc1,
            reason="приёмка",
            ref_type="Receiving",
            ref_id=42,
        )
        self.assertEqual(m.status, MovementStatus.POSTED)
        self.assertEqual(m.quantity, Decimal("10"))
        self.assertEqual(m.ref_id, "42")
        self.assertEqual(m.signed_quantity, Decimal("10"))

    def test_signed_quantity_outgoing(self):
        m = record_movement(
            movement_type=MovementType.WRITE_OFF,
            product=self.product,
            quantity=Decimal("3"),
            from_location=self.loc1,
        )
        self.assertEqual(m.signed_quantity, Decimal("-3"))

    def test_zero_quantity_rejected(self):
        with self.assertRaises(ValueError):
            record_movement(
                movement_type=MovementType.ISSUE,
                product=self.product,
                quantity=0,
            )

    def test_unknown_type_rejected(self):
        with self.assertRaises(ValueError):
            record_movement(
                movement_type="WTF",
                product=self.product,
                quantity=1,
            )


class TestMovementListView(TestCase):
    """Проверяем view через RequestFactory, минуя test client."""

    def setUp(self):
        # pytest-django подключает store_rendered_templates, который при copy()
        # контекста уходит в RecursionError на сложных шаблонах. Отключаем.
        self._template_receivers = signals.template_rendered.receivers
        signals.template_rendered.receivers = []

        self.product, self.loc1, self.loc2 = _build_fixtures()
        self.admin = User.objects.create_user(
            username="mov_admin",
            email="movadmin@test.ru",
            password="Pass1!ABCDEFGH",
            role="ADMIN",
        )
        self.factory = RequestFactory()
        record_movement(
            movement_type=MovementType.RECEIPT,
            product=self.product, quantity=5, to_location=self.loc1,
        )
        record_movement(
            movement_type=MovementType.WRITE_OFF,
            product=self.product, quantity=1, from_location=self.loc1,
            reason="брак",
        )

    def tearDown(self):
        signals.template_rendered.receivers = self._template_receivers

    def _get(self, **params):
        request = self.factory.get(reverse("movement_list"), params)
        request.user = self.admin
        return movement_list(request)

    def test_url_resolves(self):
        self.assertTrue(reverse("movement_list").endswith("/movements/"))

    def test_list_renders_html(self):
        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode("utf-8")
        self.assertIn("MOV-TEST-1", body)
        self.assertIn("Поступление", body)

    def test_filter_by_type_html(self):
        resp = self._get(type=MovementType.WRITE_OFF)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode("utf-8")
        # на странице должна быть только запись WRITE_OFF, не RECEIPT
        self.assertIn("Списание", body)
        self.assertNotIn("Поступление", body[body.find("<tbody"):body.find("</tbody>")] if "<tbody" in body else body)

    def test_search_by_sku_html(self):
        resp = self._get(q="MOV-TEST-1")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("MOV-TEST-1", resp.content.decode("utf-8"))

    def test_csv_export(self):
        # CSV-ветка возвращает HttpResponse напрямую, без рендера шаблона.
        resp = self._get(export="csv")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/csv; charset=utf-8-sig")
        body = resp.content.decode("utf-8-sig")
        self.assertIn("MOV-TEST-1", body)
        self.assertIn("Поступление", body)
        self.assertIn("Списание", body)

    def test_csv_export_filtered_by_type(self):
        resp = self._get(export="csv", type=MovementType.WRITE_OFF)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode("utf-8-sig")
        self.assertIn("Списание", body)
        self.assertNotIn("Поступление", body)
