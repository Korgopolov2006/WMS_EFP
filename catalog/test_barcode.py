"""
Тесты для модуля штрихкодов / QR / эндпоинтов.
"""
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, signals
from django.urls import reverse

from catalog.barcode_service import (
    find_product_by_code,
    get_product_code,
    render_barcode_png,
    render_qr_png,
)
from catalog.barcode_views import (
    barcode_image,
    labels_bulk_view,
    lookup_by_code,
    qr_image,
)
from catalog.models import Brand, Category, Product

User = get_user_model()


def _build_product(sku="BAR-TEST-1", oem="BAR-OEM-TEST-1", barcode_value=""):
    brand, _ = Brand.objects.get_or_create(name="BarTestBrand")
    category, _ = Category.objects.get_or_create(name="BarTestCat")
    return Product.objects.create(
        internal_sku=sku,
        name="Bar test " + sku,
        oem_number=oem,
        brand=brand,
        category=category,
        barcode=barcode_value,
    )


class TestBarcodeService(TestCase):
    def test_render_barcode_png_returns_png(self):
        png = render_barcode_png("ABC-123")
        self.assertTrue(png.startswith(b"\x89PNG"))
        self.assertGreater(len(png), 100)

    def test_render_qr_png_returns_png(self):
        png = render_qr_png("ABC-123")
        self.assertTrue(png.startswith(b"\x89PNG"))
        self.assertGreater(len(png), 100)

    def test_render_empty_raises(self):
        with self.assertRaises(ValueError):
            render_barcode_png("")
        with self.assertRaises(ValueError):
            render_qr_png("   ")

    def test_get_product_code_uses_barcode_first(self):
        p = _build_product(sku="BAR-A", oem="BAR-OEM-A", barcode_value="4607123456789")
        self.assertEqual(get_product_code(p), "4607123456789")

    def test_get_product_code_falls_back_to_sku(self):
        p = _build_product(sku="BAR-B", oem="BAR-OEM-B")
        self.assertEqual(get_product_code(p), "BAR-B")

    def test_find_by_code_priority(self):
        p1 = _build_product(sku="BAR-FIND-1", oem="BAR-OEM-1", barcode_value="100200300")
        p2 = _build_product(sku="100200300", oem="BAR-OEM-2")  # коллизия sku == barcode
        # barcode имеет приоритет над sku
        self.assertEqual(find_product_by_code("100200300").pk, p1.pk)

    def test_find_by_code_oem_fallback(self):
        p = _build_product(sku="BAR-FIND-3", oem="BAR-OEM-3", barcode_value="")
        self.assertEqual(find_product_by_code("BAR-OEM-3").pk, p.pk)

    def test_find_by_code_empty(self):
        self.assertIsNone(find_product_by_code(""))


class TestBarcodeEndpoints(TestCase):
    def setUp(self):
        # обходим Recursion в template_rendered (см. test_movements)
        self._tr_recv = signals.template_rendered.receivers
        signals.template_rendered.receivers = []

        self.product = _build_product(sku="BAR-EP-1", oem="BAR-OEM-EP-1", barcode_value="")
        self.user = User.objects.create_user(
            username="bar_user", email="bar@test.ru",
            password="Pass1!ABCDEFGH", role="ADMIN",
        )
        self.factory = RequestFactory()

    def tearDown(self):
        signals.template_rendered.receivers = self._tr_recv

    def _request(self, view, url_name, kwargs=None, **params):
        request = self.factory.get(reverse(url_name, kwargs=kwargs or {}), params)
        request.user = self.user
        if kwargs:
            return view(request, **kwargs)
        return view(request)

    def test_barcode_image_returns_png(self):
        resp = self._request(barcode_image, "catalog_barcode_image", {"sku": self.product.internal_sku})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "image/png")
        self.assertTrue(resp.content.startswith(b"\x89PNG"))

    def test_qr_image_returns_png(self):
        resp = self._request(qr_image, "catalog_qr_image", {"sku": self.product.internal_sku})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "image/png")
        self.assertTrue(resp.content.startswith(b"\x89PNG"))

    def test_barcode_image_unknown_sku_404(self):
        from django.http import Http404
        with self.assertRaises(Http404):
            self._request(barcode_image, "catalog_barcode_image", {"sku": "UNKNOWN-SKU-999"})

    def test_lookup_found(self):
        self.product.barcode = "777-888-999"
        self.product.save()
        resp = self._request(lookup_by_code, "catalog_code_lookup", code="777-888-999")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode("utf-8")
        self.assertIn('"found": true', body)
        self.assertIn("BAR-EP-1", body)

    def test_lookup_not_found(self):
        resp = self._request(lookup_by_code, "catalog_code_lookup", code="DOESNOTEXIST-XYZ")
        self.assertEqual(resp.status_code, 200)
        self.assertIn('"found": false', resp.content.decode("utf-8"))

    def test_labels_bulk_requires_ids(self):
        resp = self._request(labels_bulk_view, "catalog_labels_bulk")
        self.assertEqual(resp.status_code, 400)


class TestBarcodeUniqueConstraint(TestCase):
    def test_duplicate_barcode_rejected(self):
        from django.db import IntegrityError, transaction
        _build_product(sku="UNQ-1", oem="UNQ-OEM-1", barcode_value="123-DUP")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                _build_product(sku="UNQ-2", oem="UNQ-OEM-2", barcode_value="123-DUP")

    def test_empty_barcode_allowed_multiple(self):
        # Два товара с пустым barcode должны сосуществовать (partial unique)
        _build_product(sku="EMP-1", oem="EMP-OEM-1", barcode_value="")
        _build_product(sku="EMP-2", oem="EMP-OEM-2", barcode_value="")
        self.assertEqual(Product.objects.filter(barcode="", internal_sku__startswith="EMP-").count(), 2)
