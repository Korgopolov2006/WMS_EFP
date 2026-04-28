from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase

from .forms import ReceivingLineForm, SupplierForm


class SupplierFormTests(TestCase):
    def test_code_is_normalized_to_upper_alnum(self):
        form = SupplierForm(data={"code": " auto-trade 01 ", "name": "AutoTrade"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["code"], "AUTOTRADE01")

    def test_code_rejects_non_latin_symbols(self):
        form = SupplierForm(data={"code": "тест!!!", "name": "Supplier"})
        self.assertFalse(form.is_valid())
        self.assertIn("code", form.errors)
        self.assertIn("Код должен содержать латинские буквы и/или цифры.", form.errors["code"])


class ReceivingLineFormPieceQtyTests(SimpleTestCase):
    def test_validate_piece_qty_rejects_fraction(self):
        with self.assertRaisesMessage(ValidationError, "Ожидаемое количество должно быть целым числом (шт)."):
            ReceivingLineForm._validate_piece_qty(Decimal("1.5"), "Ожидаемое количество")

    def test_validate_piece_qty_rejects_negative_when_zero_allowed(self):
        with self.assertRaisesMessage(ValidationError, "Принятое количество не может быть отрицательным."):
            ReceivingLineForm._validate_piece_qty(Decimal("-1"), "Принятое количество", allow_zero=True)

    def test_validate_piece_qty_accepts_integer(self):
        result = ReceivingLineForm._validate_piece_qty(Decimal("3"), "Ожидаемое количество")
        self.assertEqual(result, Decimal("3"))
