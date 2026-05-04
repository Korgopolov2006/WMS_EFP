"""
Тесты импорта каталога запчастей: SyntheticPartsDriver + management-команда.
"""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from catalog.import_drivers.parts_synth import (
    SyntheticPartsDriver,
    _stable_internal_sku,
    _stable_oem,
)
from catalog.models import (
    Brand,
    Category,
    Product,
    ProductApplicability,
    VehicleMake,
    VehicleModel,
)


def _build_vehicles():
    """Создаёт минимальный набор машин для генерации запчастей."""
    ford, _ = VehicleMake.objects.get_or_create(name="TestPartsBrand-Ford")
    bmw, _ = VehicleMake.objects.get_or_create(name="TestPartsBrand-BMW")
    VehicleModel.objects.get_or_create(make=ford, name="TestPartsModel-Focus")
    VehicleModel.objects.get_or_create(make=ford, name="TestPartsModel-Mondeo")
    VehicleModel.objects.get_or_create(make=bmw, name="TestPartsModel-X5")
    return [ford, bmw]


class TestStableHelpers(TestCase):
    def test_stable_oem_deterministic(self):
        a = _stable_oem("Bosch", "OIL", "Ford-Focus-1")
        b = _stable_oem("Bosch", "OIL", "Ford-Focus-1")
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("BOS-OIL-"))

    def test_stable_oem_different_inputs(self):
        a = _stable_oem("Bosch", "OIL", "Ford-Focus-1")
        b = _stable_oem("Bosch", "OIL", "Ford-Mondeo-2")
        self.assertNotEqual(a, b)

    def test_stable_internal_sku_format(self):
        sku = _stable_internal_sku("BOS-OIL-12345678")
        self.assertEqual(sku, "SYN-BOS-OIL-12345678")


class TestSyntheticPartsDriver(TestCase):
    def setUp(self):
        _build_vehicles()
        self.driver = SyntheticPartsDriver(per_model_default=4)

    def test_iter_categories_returns_parents_and_children(self):
        cats = list(self.driver.iter_categories())
        names = {c.name for c in cats}
        self.assertIn("Двигатель", names)
        self.assertIn("Тормозная система", names)
        self.assertIn("Масляный фильтр", names)
        self.assertIn("Тормозные колодки", names)

    def test_iter_parts_yields_entries(self):
        parts = list(self.driver.iter_parts(makes=["TestPartsBrand-Ford"], per_model_limit=3))
        # 2 модели Ford * 3 запчасти
        self.assertEqual(len(parts), 6)
        for p in parts:
            self.assertTrue(p.oem_number)
            self.assertTrue(p.internal_sku.startswith("SYN-"))
            self.assertTrue(p.brand_name)
            self.assertTrue(p.category_name)
            self.assertEqual(len(p.applicable_to), 1)

    def test_iter_parts_unique_oems(self):
        parts = list(self.driver.iter_parts(per_model_limit=8))
        oems = [p.oem_number for p in parts]
        self.assertEqual(len(set(oems)), len(oems), "OEM-номера должны быть уникальны")

    def test_iter_parts_filter_by_make(self):
        parts = list(self.driver.iter_parts(makes=["TestPartsBrand-BMW"], per_model_limit=2))
        self.assertEqual(len(parts), 2)  # 1 модель BMW × 2 запчасти

    def test_iter_parts_filter_by_models(self):
        parts = list(self.driver.iter_parts(
            makes=["TestPartsBrand-Ford"],
            models=["TestPartsModel-Focus"],
            per_model_limit=5,
        ))
        self.assertEqual(len(parts), 5)
        for p in parts:
            self.assertEqual(p.applicable_to[0][1], "TestPartsModel-Focus")


class TestImportPartsCommand(TestCase):
    def setUp(self):
        _build_vehicles()

    def _run(self, *args):
        out = StringIO()
        call_command("import_parts", *args, stdout=out)
        return out.getvalue()

    def test_command_creates_products(self):
        before = Product.objects.count()
        out = self._run("--makes", "TestPartsBrand-Ford", "--per-model", "3")
        self.assertGreater(Product.objects.count(), before)
        self.assertIn("Готово", out)

    def test_command_creates_categories(self):
        before = Category.objects.count()
        self._run("--makes", "TestPartsBrand-BMW", "--per-model", "2")
        self.assertGreater(Category.objects.count(), before)

    def test_command_links_applicability(self):
        self._run("--makes", "TestPartsBrand-BMW", "--per-model", "2")
        # для X5 должна появиться применимость
        x5 = VehicleModel.objects.get(make__name="TestPartsBrand-BMW", name="TestPartsModel-X5")
        self.assertGreater(
            ProductApplicability.objects.filter(vehicle_model=x5).count(),
            0,
        )

    def test_command_idempotent(self):
        self._run("--makes", "TestPartsBrand-Ford", "--per-model", "3")
        first = Product.objects.filter(internal_sku__startswith="SYN-").count()
        self._run("--makes", "TestPartsBrand-Ford", "--per-model", "3")
        # повторный прогон ничего не добавляет
        self.assertEqual(
            Product.objects.filter(internal_sku__startswith="SYN-").count(),
            first,
        )

    def test_command_dry_run_does_not_write(self):
        before_p = Product.objects.count()
        before_b = Brand.objects.count()
        self._run("--makes", "TestPartsBrand-Ford", "--per-model", "3", "--dry-run")
        self.assertEqual(Product.objects.count(), before_p)
        self.assertEqual(Brand.objects.count(), before_b)

    def test_command_limit(self):
        self._run("--makes", "TestPartsBrand-Ford", "--per-model", "10", "--limit", "4")
        # должно быть создано не больше 4 товаров
        synth_products = Product.objects.filter(internal_sku__startswith="SYN-").count()
        self.assertLessEqual(synth_products, 4)

    def test_command_creates_brands(self):
        before = Brand.objects.count()
        self._run("--makes", "TestPartsBrand-Ford", "--per-model", "5")
        # синтезатор использует пул брендов запчастей (Mann, Bosch, Brembo и т.д.)
        self.assertGreater(Brand.objects.count(), before)
