from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.constants import Roles
from catalog.models import Brand, Category, Product
from .forms import OrderForm, OrderLineForm
from .models import Order, OrderLine, OrderPriority
from .services import PickingService


User = get_user_model()


class OrderFormTests(TestCase):
    def _make_form(self, **overrides):
        data = {
            "number": "",
            "customer_name": "Иван Петров",
            "customer_phone": "+7 (999) 123-45-67",
            "customer_email": "",
            "priority": OrderPriority.NORMAL,
            "shipping_due_at": "",
            "source": "MANUAL",
            "external_id": "",
            "note": "",
        }
        data.update(overrides)
        return OrderForm(data=data)

    def test_customer_phone_is_required(self):
        form = self._make_form(customer_phone="")

        self.assertFalse(form.is_valid())
        self.assertIn("customer_phone", form.errors)

    def test_customer_phone_must_have_enough_digits(self):
        form = self._make_form(customer_phone="12345")

        self.assertFalse(form.is_valid())
        self.assertIn("Телефон должен содержать минимум 10 цифр.", form.errors["customer_phone"])

    def test_manual_order_can_have_empty_external_id(self):
        form = self._make_form(source="MANUAL", external_id="")

        self.assertTrue(form.is_valid(), form.errors)

    def test_order_number_is_generated_automatically(self):
        form = self._make_form(number="", note="Позвонить перед выдачей")

        self.assertTrue(form.is_valid(), form.errors)
        order = form.save(commit=False)
        self.assertTrue(order.number.startswith("ORD-"))
        self.assertEqual(order.note, "Позвонить перед выдачей")

    def test_order_priority_and_due_date_are_saved(self):
        form = self._make_form(priority=OrderPriority.URGENT, shipping_due_at="2026-05-05T12:30")

        self.assertTrue(form.is_valid(), form.errors)
        order = form.save(commit=False)
        self.assertEqual(order.priority, OrderPriority.URGENT)
        self.assertIsNotNone(order.shipping_due_at)

    def test_source_has_friendly_choices(self):
        choices = dict(OrderForm.SOURCE_CHOICES)

        self.assertEqual(choices["MANUAL"], "Вручную в WMS")
        self.assertEqual(choices["PHONE"], "Звонок клиента")


class OrderLineFormTests(TestCase):
    def setUp(self):
        brand = Brand.objects.create(name="DENSO")
        category = Category.objects.create(name="Alternator")
        self.product = Product.objects.create(
            internal_sku="SKU-100",
            name="Alternator 100A",
            oem_number="OEM-100",
            analog_number="ALT-100",
            brand=brand,
            category=category,
        )

    def _make_form(self, qty_ordered):
        return OrderLineForm(
            data={
                "product": self.product.pk,
                "qty_ordered": qty_ordered,
                "price": "100.00",
            }
        )

    def test_qty_ordered_must_be_integer(self):
        form = self._make_form("1.5")
        self.assertFalse(form.is_valid())
        self.assertIn("qty_ordered", form.errors)
        self.assertIn("Количество должно быть целым числом (шт).", form.errors["qty_ordered"])

    def test_qty_ordered_must_be_positive(self):
        form = self._make_form("0")
        self.assertFalse(form.is_valid())
        self.assertIn("qty_ordered", form.errors)
        self.assertIn("Количество должно быть больше нуля.", form.errors["qty_ordered"])

    def test_qty_ordered_valid_value(self):
        form = self._make_form("2")
        self.assertTrue(form.is_valid(), form.errors)


class PickingServiceTests(TestCase):
    def setUp(self):
        brand = Brand.objects.create(name="DENSO")
        category = Category.objects.create(name="Filter")
        self.product = Product.objects.create(
            internal_sku="SKU-PICK-100",
            name="Filter 100",
            oem_number="OEM-PICK-100",
            analog_number="",
            brand=brand,
            category=category,
            packaging_type=Product.PackagingType.SMALL,
        )
        self.user = User.objects.create_user(
            username="sales_for_pick",
            email="sales_for_pick@example.com",
            password="Pass1!ABCDEFGH",
            role=Roles.SALES_MANAGER,
        )

    def test_picking_tasks_inherit_order_priority_and_due_date(self):
        due_date = timezone.now() + timedelta(hours=4)
        order = Order.objects.create(
            number="ORD-TEST-PRIORITY",
            customer_name="Иван Петров",
            customer_phone="+7 (999) 123-45-67",
            priority=OrderPriority.HIGH,
            shipping_due_at=due_date,
            created_by=self.user,
        )
        OrderLine.objects.create(order=order, product=self.product, qty_ordered=2)

        tasks = PickingService.create_picking_tasks_for_order(order)

        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].priority, OrderPriority.HIGH)
        self.assertEqual(tasks[0].due_date, due_date)
