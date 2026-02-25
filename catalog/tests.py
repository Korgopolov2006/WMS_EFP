from django.core.exceptions import ValidationError
from django.test import TestCase

from .models import Brand, Category, Product
from .normalization import normalize_part_number
from .product_validation import validate_product_numbers_uniqueness


class NormalizePartNumberTests(TestCase):
    def test_returns_empty_string_for_none_or_blank(self):
        self.assertEqual(normalize_part_number(None), "")
        self.assertEqual(normalize_part_number("   "), "")

    def test_uppercases_and_removes_non_alnum(self):
        self.assertEqual(normalize_part_number(" ab-12 / cd "), "AB12CD")


class ProductValidationTests(TestCase):
    def setUp(self):
        self.brand = Brand.objects.create(name="BOSCH")
        self.category = Category.objects.create(name="Starter")
        self.existing = Product.objects.create(
            internal_sku="SKU-001",
            name="Starter 1",
            oem_number="AB-123",
            analog_number="XZ-987",
            brand=self.brand,
            category=self.category,
        )

    def test_raises_when_oem_missing(self):
        with self.assertRaisesMessage(ValidationError, "OEM номер обязателен."):
            validate_product_numbers_uniqueness(oem_number="", analog_number="ANY-1")

    def test_raises_when_analog_matches_oem_after_normalization(self):
        with self.assertRaisesMessage(ValidationError, "Номер аналога не должен совпадать с OEM после нормализации."):
            validate_product_numbers_uniqueness(oem_number="AB 123", analog_number="ab-123")

    def test_raises_when_duplicate_found(self):
        with self.assertRaisesMessage(ValidationError, "Обнаружен дубликат по OEM/аналогу"):
            validate_product_numbers_uniqueness(oem_number="ab123", analog_number="")

    def test_allows_unique_numbers(self):
        # Should not raise.
        validate_product_numbers_uniqueness(oem_number="UNQ-777", analog_number="ALT-999")

    def test_product_save_sets_normalized_fields(self):
        product = Product.objects.create(
            internal_sku="SKU-002",
            name="Starter 2",
            oem_number="Qw- 12",
            analog_number="Z-9",
            brand=self.brand,
            category=self.category,
        )
        self.assertEqual(product.oem_number_normalized, "QW12")
        self.assertEqual(product.analog_number_normalized, "Z9")
