from decimal import Decimal
import json

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from accounts.constants import Roles
from catalog.models import Brand, Category, Product, StorageLocation, StorageZone, StorageZoneType
from inventory.models import Inventory, Stock
from inventory.views import inventory_product_hint


User = get_user_model()


class InventoryProductHintTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="inv_hint_admin",
            email="inv_hint_admin@example.com",
            password="Pass1!ABCDEFGH",
            role=Roles.ADMIN,
            is_superuser=True,
        )
        zone_type = StorageZoneType.objects.create(code="INV-HINT", name="Инвентаризация")
        self.zone = StorageZone.objects.create(code="INV-ZONE", name="Зона", zone_type=zone_type)
        self.location = StorageLocation.objects.create(zone=self.zone, code="INV-A01", name="Первая полка")
        brand = Brand.objects.create(name="HintBrand")
        category = Category.objects.create(name="HintCategory")
        self.product = Product.objects.create(
            internal_sku="INV-HINT-001",
            name="Тестовый фильтр",
            oem_number="OEM-HINT-001",
            barcode="4607000000001",
            brand=brand,
            category=category,
        )
        Stock.objects.create(
            product=self.product,
            storage_location=self.location,
            qty_available=Decimal("7.00"),
        )
        self.inventory = Inventory.objects.create(
            number="INV-HINT-DOC",
            zone=self.zone,
            created_by=self.user,
        )
        self.factory = RequestFactory()

    def test_hint_returns_product_location_qty_and_code_urls(self):
        request = self.factory.get("/inventory/inventory/1/product-hint/", {"q": "OEM-HINT"})
        request.user = self.user

        response = inventory_product_hint(request, self.inventory.pk)

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content.decode("utf-8"))
        self.assertEqual(len(data["products"]), 1)
        item = data["products"][0]
        self.assertEqual(item["sku"], "INV-HINT-001")
        self.assertEqual(item["primary_location"]["code"], "INV-A01")
        self.assertEqual(item["primary_location"]["qty_book"], "7")
        self.assertIn("/catalog/codes/barcode/INV-HINT-001.png", item["barcode_url"])
        self.assertIn("/catalog/codes/qr/INV-HINT-001.png", item["qr_url"])
