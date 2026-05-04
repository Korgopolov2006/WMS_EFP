from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, signals
from django.urls import reverse

from accounts.constants import Roles
from catalog.models import Brand, Category, Product, StorageLocation, StorageZone, StorageZoneType
from inventory.models import Stock
from inventory.views import stock_list


User = get_user_model()


class StockListFriendlyFilterTests(TestCase):
    def setUp(self):
        self._template_receivers = signals.template_rendered.receivers
        signals.template_rendered.receivers = []

        self.user = User.objects.create_user(
            username="stock_filter_admin",
            email="stock_filter_admin@example.com",
            password="Pass1!ABCDEFGH",
            role=Roles.ADMIN,
        )
        self.factory = RequestFactory()
        zone_type = StorageZoneType.objects.create(code="STOCK-FILTER", name="Остатки")
        zone = StorageZone.objects.create(code="SF-ZONE", name="Зона остатков", zone_type=zone_type)
        self.loc_a = StorageLocation.objects.create(zone=zone, code="SF-A01", name="Полка A")
        self.loc_b = StorageLocation.objects.create(zone=zone, code="SF-B02", name="Полка B")
        brand = Brand.objects.create(name="StockFilterBrand")
        category = Category.objects.create(name="StockFilterCategory")
        self.product_a = Product.objects.create(
            internal_sku="STOCK-ALPHA",
            name="Фильтр Alpha",
            oem_number="OEM-ALPHA",
            barcode="BAR-ALPHA",
            brand=brand,
            category=category,
        )
        self.product_b = Product.objects.create(
            internal_sku="STOCK-BETA",
            name="Диск Beta",
            oem_number="OEM-BETA",
            barcode="BAR-BETA",
            brand=brand,
            category=category,
        )
        Stock.objects.create(product=self.product_a, storage_location=self.loc_a, qty_available=Decimal("3"))
        Stock.objects.create(product=self.product_b, storage_location=self.loc_b, qty_available=Decimal("5"))

    def tearDown(self):
        signals.template_rendered.receivers = self._template_receivers

    def _get(self, **params):
        request = self.factory.get(reverse("stock_list"), params)
        request.user = self.user
        return stock_list(request)

    def test_product_filter_uses_sku_oem_name_or_barcode_not_id(self):
        response = self._get(product="OEM-ALPHA")

        body = response.content.decode("utf-8")
        self.assertEqual(response.status_code, 200)
        self.assertIn("STOCK-ALPHA", body)
        self.assertNotIn("STOCK-BETA", body)

    def test_location_filter_uses_human_location_code(self):
        response = self._get(location="SF-B02")

        body = response.content.decode("utf-8")
        self.assertEqual(response.status_code, 200)
        self.assertIn("STOCK-BETA", body)
        self.assertNotIn("STOCK-ALPHA", body)

    def test_legacy_id_filters_still_work(self):
        response = self._get(product_id=str(self.product_a.pk), location_id=str(self.loc_a.pk))

        body = response.content.decode("utf-8")
        self.assertEqual(response.status_code, 200)
        self.assertIn("STOCK-ALPHA", body)
        self.assertNotIn("STOCK-BETA", body)
