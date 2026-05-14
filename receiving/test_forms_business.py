"""
Тесты валидации форм receiving — ReceivingForm и ReceivingLineForm.

Покрывает:
 * ReceivingForm — выбор склада, поставщика, generate_next_supplier_doc_number
 * ReceivingLineForm — qty_expected, qty_received, проверка storage_location
 * SupplierForm — нормализация кода
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
from receiving.forms import ReceivingForm, ReceivingLineForm, SupplierForm
from receiving.models import Receiving, Supplier


User = get_user_model()


class FormsFixturesMixin:
    @classmethod
    def setup(cls):
        cls.admin = User.objects.create_user(
            username="frm_admin", email="fa@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.ADMIN, is_superuser=True,
        )
        branch = Branch.objects.create(code="BR1", name="Главный")
        cls.warehouse = Warehouse.objects.create(branch=branch, code="WH1", name="WH1")
        zt, _ = StorageZoneType.objects.get_or_create(code="CELL", defaults={"name": "Ячейка"})
        zone = StorageZone.objects.create(
            warehouse=cls.warehouse, code="Z1", name="Z1", zone_type=zt,
        )
        cls.location = StorageLocation.objects.create(zone=zone, code="L1", name="L1")
        cls.supplier = Supplier.objects.create(code="ACME", name="ACME Ltd")
        brand = Brand.objects.create(name="DENSO")
        cat = Category.objects.create(name="Generic")
        cls.product = Product.objects.create(
            internal_sku="SKU-F-1", name="Товар",
            oem_number="OEM-F-1", brand=brand, category=cat,
            packaging_type=Product.PackagingType.SMALL,
        )


# ════════════════════════════════════════════════════════════════════
# ReceivingForm
# ════════════════════════════════════════════════════════════════════
class ReceivingFormTests(FormsFixturesMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.setup()

    def test_init_for_new_doc_sets_defaults(self):
        form = ReceivingForm(user=self.admin)
        # initial number проставлен
        self.assertTrue(str(form.initial.get("number", "")).startswith("RCV-"))
        # expected_at = сегодня
        self.assertEqual(form.initial.get("expected_at"), timezone.localdate())

    def test_warehouse_required(self):
        form = ReceivingForm(
            data={
                "number": "",
                "supplier_doc_no": "",
                "supplier": str(self.supplier.pk),
                "warehouse": "",  # не выбран
                "expected_at": "2026-05-15",
            },
            user=self.admin,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("warehouse", form.errors)

    def test_valid_form_saves_receiving(self):
        form = ReceivingForm(
            data={
                "number": "",
                "supplier_doc_no": "",
                "supplier": str(self.supplier.pk),
                "warehouse": str(self.warehouse.pk),
                "expected_at": "2026-05-15",
            },
            user=self.admin,
        )
        self.assertTrue(form.is_valid(), form.errors)
        obj = form.save(commit=False)
        obj.created_by = self.admin
        obj.save()
        self.assertEqual(obj.supplier_name, self.supplier.name)
        self.assertEqual(obj.warehouse_id, self.warehouse.id)
        self.assertIsNotNone(obj.expected_at)

    def test_supplier_doc_no_auto_generated_on_save(self):
        form = ReceivingForm(
            data={
                "number": "",
                "supplier_doc_no": "",
                "supplier": str(self.supplier.pk),
                "warehouse": str(self.warehouse.pk),
            },
            user=self.admin,
        )
        self.assertTrue(form.is_valid(), form.errors)
        obj = form.save(commit=False)
        obj.created_by = self.admin
        obj.save()
        self.assertIn("ACME", obj.supplier_doc_no.upper())


# ════════════════════════════════════════════════════════════════════
# ReceivingLineForm — clean_storage_location
# ════════════════════════════════════════════════════════════════════
class ReceivingLineFormStorageLocationTests(FormsFixturesMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.setup()

    def test_valid_line_with_matching_warehouse(self):
        form = ReceivingLineForm(
            data={
                "product": str(self.product.pk),
                "supplier_sku": "ACME-001",
                "qty_expected": "5",
                "qty_received": "5",
                "storage_location": str(self.location.pk),
            },
            user=self.admin,
            warehouse=self.warehouse,
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_line_rejects_location_from_wrong_warehouse(self):
        # Создаём место в другом складе
        wh2 = Warehouse.objects.create(
            branch=self.warehouse.branch, code="WH2", name="WH2",
        )
        zt, _ = StorageZoneType.objects.get_or_create(
            code="CELL", defaults={"name": "Ячейка"},
        )
        z2 = StorageZone.objects.create(warehouse=wh2, code="Z2", name="Z2", zone_type=zt)
        loc2 = StorageLocation.objects.create(zone=z2, code="L2", name="L2")

        form = ReceivingLineForm(
            data={
                "product": str(self.product.pk),
                "supplier_sku": "ACME-001",
                "qty_expected": "5",
                "qty_received": "5",
                "storage_location": str(loc2.pk),
            },
            user=self.admin,
            warehouse=self.warehouse,
        )
        # форма либо не валидна, либо queryset не включает чужое место
        # Проверяем что не сохранится с этим местом
        if form.is_valid():
            # Тогда queryset отфильтровал поле
            self.assertNotEqual(
                form.cleaned_data.get("storage_location"), loc2,
            )

    def test_line_qty_expected_must_be_positive(self):
        form = ReceivingLineForm(
            data={
                "product": str(self.product.pk),
                "supplier_sku": "ACME-001",
                "qty_expected": "0",
                "qty_received": "0",
                "storage_location": str(self.location.pk),
            },
            user=self.admin,
            warehouse=self.warehouse,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("qty_expected", form.errors)

    def test_line_qty_received_can_be_zero(self):
        form = ReceivingLineForm(
            data={
                "product": str(self.product.pk),
                "supplier_sku": "ACME-001",
                "qty_expected": "5",
                "qty_received": "0",
                "storage_location": str(self.location.pk),
            },
            user=self.admin,
            warehouse=self.warehouse,
        )
        # qty_received=0 разрешено (товар не принят ещё)
        self.assertTrue(form.is_valid(), form.errors)

    def test_line_qty_received_fractional_rejected(self):
        form = ReceivingLineForm(
            data={
                "product": str(self.product.pk),
                "supplier_sku": "ACME-001",
                "qty_expected": "5",
                "qty_received": "2.5",
                "storage_location": str(self.location.pk),
            },
            user=self.admin,
            warehouse=self.warehouse,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("qty_received", form.errors)

    def test_line_form_suggests_location_for_product_initial(self):
        form = ReceivingLineForm(
            initial={"product": self.product.pk},
            user=self.admin,
            warehouse=self.warehouse,
        )
        # форма подсказала место хранения автоматом (suggest_storage_location)
        suggested = form.initial.get("storage_location")
        self.assertEqual(suggested, self.location.pk)


# ════════════════════════════════════════════════════════════════════
# SupplierForm — дополнение к существующим тестам
# ════════════════════════════════════════════════════════════════════
class SupplierFormAdditionalTests(TestCase):
    def test_empty_code_after_normalization_rejected(self):
        form = SupplierForm(data={"code": "   ", "name": "X"})
        self.assertFalse(form.is_valid())
        self.assertIn("code", form.errors)

    def test_long_code_rejected_by_max_length(self):
        # Поле модели имеет max_length=24 — Django валидирует ДО clean_code
        form = SupplierForm(
            data={"code": "A" * 50, "name": "X"},
        )
        self.assertFalse(form.is_valid())
        self.assertIn("code", form.errors)

    def test_mixed_case_normalizes_to_upper(self):
        form = SupplierForm(data={"code": "MixedCase01", "name": "X"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["code"], "MIXEDCASE01")
