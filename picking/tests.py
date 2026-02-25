from django.test import TestCase

from catalog.models import Brand, Category, Product
from .forms import OrderLineForm


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
