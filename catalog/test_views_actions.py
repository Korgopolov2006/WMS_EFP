"""
Smoke + action тесты каталога: списки и создание справочников.
Покрывает в основном маршруты admin_home / brand / category / vehicle_make/model / zone_type.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from accounts.constants import Roles
from catalog.models import (
    Branch,
    Brand,
    Category,
    Product,
    StorageZoneType,
    VehicleMake,
    VehicleModel,
    Warehouse,
)


User = get_user_model()


class CatalogViewsBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="cat_admin", email="ca@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.ADMIN, is_superuser=True,
        )
        cls.picker = User.objects.create_user(
            username="cat_pck", email="cp@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.SMALL_PARTS_PICKER,
        )

    def _client(self, user):
        c = Client()
        c.force_login(user)
        return c


class CatalogAdminPagesTests(CatalogViewsBase):
    URLS = [
        "catalog_admin_home",
        "catalog_brand_list",
        "catalog_brand_create",
        "catalog_category_list",
        "catalog_category_create",
        "catalog_vehicle_make_list",
        "catalog_vehicle_make_create",
        "catalog_vehicle_model_list",
        "catalog_vehicle_model_create",
        "catalog_zone_type_list",
        "catalog_zone_type_create",
        "catalog_storage_map",
        "catalog_product_list",
        "catalog_product_audit_list",
        "catalog_product_create",
    ]

    def test_all_admin_pages_render(self):
        client = self._client(self.admin)
        for name in self.URLS:
            response = client.get(reverse(name))
            self.assertIn(
                response.status_code, (200, 302),
                f"{name} → {response.status_code}",
            )

    def test_picker_blocked_from_catalog_admin(self):
        client = self._client(self.picker)
        response = client.get(reverse("catalog_admin_home"))
        self.assertEqual(response.status_code, 403)


class CatalogBrandTests(CatalogViewsBase):
    def test_create_brand(self):
        client = self._client(self.admin)
        client.post(reverse("catalog_brand_create"), {
            "name": "BRAND-TEST-1",
        })
        self.assertTrue(Brand.objects.filter(name="BRAND-TEST-1").exists())

    def test_update_brand(self):
        brand = Brand.objects.create(name="OldBrand")
        client = self._client(self.admin)
        client.post(reverse("catalog_brand_update", args=[brand.pk]), {
            "name": "NewBrand",
        })
        brand.refresh_from_db()
        self.assertEqual(brand.name, "NewBrand")

    def test_brand_list_search(self):
        Brand.objects.create(name="DENSO-X")
        client = self._client(self.admin)
        response = client.get(reverse("catalog_brand_list"), {"q": "DENSO"})
        self.assertEqual(response.status_code, 200)


class CatalogCategoryTests(CatalogViewsBase):
    def test_create_category(self):
        client = self._client(self.admin)
        client.post(reverse("catalog_category_create"), {
            "name": "Категория А",
        })
        self.assertTrue(Category.objects.filter(name="Категория А").exists())

    def test_update_category(self):
        cat = Category.objects.create(name="Старая")
        client = self._client(self.admin)
        client.post(reverse("catalog_category_update", args=[cat.pk]), {
            "name": "Новая",
        })
        cat.refresh_from_db()
        self.assertEqual(cat.name, "Новая")


class CatalogVehicleTests(CatalogViewsBase):
    def test_create_vehicle_make(self):
        client = self._client(self.admin)
        client.post(reverse("catalog_vehicle_make_create"), {
            "name": "Toyota",
        })
        self.assertTrue(VehicleMake.objects.filter(name="Toyota").exists())

    def test_create_vehicle_model(self):
        make, _ = VehicleMake.objects.get_or_create(name="Toyota")
        client = self._client(self.admin)
        client.post(reverse("catalog_vehicle_model_create"), {
            "make": str(make.pk),
            "name": "Camry",
        })
        self.assertTrue(VehicleModel.objects.filter(name="Camry").exists())


class CatalogZoneTypeTests(CatalogViewsBase):
    def test_create_zone_type(self):
        client = self._client(self.admin)
        client.post(reverse("catalog_zone_type_create"), {
            "code": "TESTZONE",
            "name": "Тестовая зона",
            "sort_order": "200",
        })
        self.assertTrue(StorageZoneType.objects.filter(code="TESTZONE").exists())


class CatalogProductCreateTests(CatalogViewsBase):
    def test_create_product(self):
        brand = Brand.objects.create(name="DENSO")
        cat = Category.objects.create(name="Tests")
        client = self._client(self.admin)
        client.post(reverse("catalog_product_create"), {
            "internal_sku": "SKU-CREATED-1",
            "name": "Новый товар",
            "oem_number": "OEM-NEW",
            "brand": str(brand.pk),
            "category": str(cat.pk),
            "packaging_type": "SMALL",
        })
        self.assertTrue(Product.objects.filter(internal_sku="SKU-CREATED-1").exists())

    def test_product_list_search(self):
        brand = Brand.objects.create(name="X")
        cat = Category.objects.create(name="Y")
        Product.objects.create(
            internal_sku="UNIQUE-FOR-SEARCH", name="X",
            oem_number="X1", brand=brand, category=cat,
        )
        client = self._client(self.admin)
        response = client.get(reverse("catalog_product_list"), {"q": "UNIQUE-FOR"})
        self.assertEqual(response.status_code, 200)


# ════════════════════════════════════════════════════════════════════
# CatalogForm tests
# ════════════════════════════════════════════════════════════════════
class CatalogFormsTests(TestCase):
    """Тесты валидации catalog/forms.py."""

    def test_product_form_requires_sku(self):
        from catalog.forms import ProductForm
        form = ProductForm(data={
            "internal_sku": "",
            "name": "X",
            "oem_number": "Y",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("internal_sku", form.errors)

    def test_product_form_valid_minimal(self):
        from catalog.forms import ProductForm
        brand = Brand.objects.create(name="DZ")
        cat = Category.objects.create(name="C")
        form = ProductForm(data={
            "internal_sku": "FORM-SKU-1",
            "name": "Из формы",
            "oem_number": "OEM-FRM-1",
            "brand": brand.pk,
            "category": cat.pk,
            "packaging_type": "SMALL",
        })
        self.assertTrue(form.is_valid(), form.errors)
