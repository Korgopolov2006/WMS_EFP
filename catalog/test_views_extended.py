"""
Расширенные тесты catalog views.

Покрывает:
 * product_update — update с changed_data + log_product_change
 * product_xref / product_xref_delete — CRUD связей
 * product_audit_list — лог изменений
 * storage_map — табличный/3D режим, фильтр по складу
 * zone_type_update — обновление справочника
 * brand/category/vehicle update с валидацией
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
    ProductChangeLog,
    ProductCrossReference,
    StorageZone,
    StorageZoneType,
    VehicleMake,
    VehicleModel,
    Warehouse,
    WarehouseAccess,
)


User = get_user_model()


class CatalogExtendedBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="cx_admin", email="cxa@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.ADMIN, is_superuser=True,
        )
        cls.brand = Brand.objects.create(name="DENSO")
        cls.category = Category.objects.create(name="Generic")
        cls.product = Product.objects.create(
            internal_sku="CX-SKU-1", name="Товар", oem_number="OEM-CX-1",
            brand=cls.brand, category=cls.category,
        )

    def _client(self):
        c = Client()
        c.force_login(self.admin)
        return c


# ════════════════════════════════════════════════════════════════════
# product_update
# ════════════════════════════════════════════════════════════════════
class ProductUpdateTests(CatalogExtendedBase):
    def test_get_update_form(self):
        client = self._client()
        response = client.get(
            reverse("catalog_product_update", args=[self.product.pk]),
        )
        self.assertEqual(response.status_code, 200)

    def test_post_updates_product(self):
        client = self._client()
        response = client.post(
            reverse("catalog_product_update", args=[self.product.pk]),
            {
                "internal_sku": self.product.internal_sku,
                "name": "Обновлённое название",
                "oem_number": self.product.oem_number,
                "brand": str(self.brand.pk),
                "category": str(self.category.pk),
                "packaging_type": "SMALL",
            },
        )
        self.assertIn(response.status_code, (200, 302))
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, "Обновлённое название")
        # ChangeLog создан
        self.assertTrue(ProductChangeLog.objects.filter(product=self.product).exists())


# ════════════════════════════════════════════════════════════════════
# product_xref CRUD
# ════════════════════════════════════════════════════════════════════
class ProductXrefTests(CatalogExtendedBase):
    def setUp(self):
        self.analog = Product.objects.create(
            internal_sku="CX-ANALOG-1", name="Аналог",
            oem_number="OEM-ANALOG", brand=self.brand, category=self.category,
        )

    def test_get_xref_list(self):
        client = self._client()
        response = client.get(
            reverse("catalog_product_xref", args=[self.product.pk]),
        )
        self.assertEqual(response.status_code, 200)

    def test_post_create_xref(self):
        client = self._client()
        client.post(
            reverse("catalog_product_xref", args=[self.product.pk]),
            {
                "to_product": str(self.analog.pk),
                "relation_type": "ANALOG",
                "note": "Полный аналог",
            },
        )
        self.assertTrue(
            ProductCrossReference.objects.filter(
                from_product=self.product, to_product=self.analog,
            ).exists()
        )

    def test_xref_filter_by_q(self):
        ProductCrossReference.objects.create(
            from_product=self.product, to_product=self.analog,
            relation_type="ANALOG", note="Заметка",
        )
        client = self._client()
        response = client.get(
            reverse("catalog_product_xref", args=[self.product.pk]),
            {"q": "Заметка"},
        )
        self.assertEqual(response.status_code, 200)

    def test_xref_delete(self):
        xref = ProductCrossReference.objects.create(
            from_product=self.product, to_product=self.analog,
            relation_type="ANALOG",
        )
        client = self._client()
        client.post(
            reverse("catalog_product_xref_delete",
                    args=[self.product.pk, xref.pk]),
        )
        self.assertFalse(
            ProductCrossReference.objects.filter(pk=xref.pk).exists()
        )

    def test_xref_delete_with_q_preserves_filter(self):
        xref = ProductCrossReference.objects.create(
            from_product=self.product, to_product=self.analog,
            relation_type="ANALOG",
        )
        client = self._client()
        response = client.post(
            reverse("catalog_product_xref_delete",
                    args=[self.product.pk, xref.pk]) + "?q=test",
        )
        self.assertEqual(response.status_code, 302)


# ════════════════════════════════════════════════════════════════════
# product_audit_list
# ════════════════════════════════════════════════════════════════════
class ProductAuditListTests(CatalogExtendedBase):
    def test_renders_audit_log(self):
        ProductChangeLog.objects.create(
            product=self.product, changed_by=self.admin,
            action=ProductChangeLog.Action.CREATE,
            changed_fields={"name": "X"},
        )
        client = self._client()
        response = client.get(reverse("catalog_product_audit_list"))
        self.assertEqual(response.status_code, 200)

    def test_filter_audit_by_q(self):
        client = self._client()
        response = client.get(
            reverse("catalog_product_audit_list"), {"q": self.product.internal_sku},
        )
        self.assertEqual(response.status_code, 200)


# ════════════════════════════════════════════════════════════════════
# storage_map
# ════════════════════════════════════════════════════════════════════
class StorageMapTests(CatalogExtendedBase):
    def setUp(self):
        branch = Branch.objects.create(code="BR1", name="Главный")
        self.warehouse = Warehouse.objects.create(
            branch=branch, code="WH1", name="WH1",
        )
        WarehouseAccess.objects.create(
            user=self.admin, warehouse=self.warehouse,
            access_level=WarehouseAccess.AccessLevel.ADMIN,
        )
        self.admin.branches.add(branch)
        zt, _ = StorageZoneType.objects.get_or_create(
            code="CELL", defaults={"name": "Ячейка"},
        )
        self.zone = StorageZone.objects.create(
            warehouse=self.warehouse, code="Z1", name="Z1", zone_type=zt,
        )

    def test_table_view(self):
        client = self._client()
        response = client.get(
            reverse("catalog_storage_map"),
            {"warehouse_id": str(self.warehouse.pk), "view": "table"},
        )
        self.assertEqual(response.status_code, 200)

    def test_3d_view_redirects(self):
        client = self._client()
        response = client.get(
            reverse("catalog_storage_map"),
            {"warehouse_id": str(self.warehouse.pk), "view": "3d"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/3d/", response["Location"])

    def test_search_filter(self):
        client = self._client()
        response = client.get(
            reverse("catalog_storage_map"),
            {"warehouse_id": str(self.warehouse.pk), "q": "Z1"},
        )
        self.assertEqual(response.status_code, 200)

    def test_no_warehouse_id_uses_first(self):
        client = self._client()
        response = client.get(reverse("catalog_storage_map"))
        self.assertEqual(response.status_code, 200)

    def test_invalid_warehouse_id(self):
        client = self._client()
        response = client.get(
            reverse("catalog_storage_map"),
            {"warehouse_id": "not-a-number"},
        )
        self.assertEqual(response.status_code, 200)


# ════════════════════════════════════════════════════════════════════
# zone_type_update
# ════════════════════════════════════════════════════════════════════
class ZoneTypeUpdateTests(CatalogExtendedBase):
    def test_update_zone_type(self):
        zt, _ = StorageZoneType.objects.get_or_create(
            code="UPD-ZT", defaults={"name": "Старое имя"},
        )
        client = self._client()
        client.post(
            reverse("catalog_zone_type_update", args=[zt.pk]),
            {"code": "UPD-ZT", "name": "Новое имя", "sort_order": "100"},
        )
        zt.refresh_from_db()
        self.assertEqual(zt.name, "Новое имя")


# ════════════════════════════════════════════════════════════════════
# vehicle_make / vehicle_model update
# ════════════════════════════════════════════════════════════════════
class VehicleUpdateTests(CatalogExtendedBase):
    def test_update_vehicle_make(self):
        make, _ = VehicleMake.objects.get_or_create(name="HondaUnique")
        client = self._client()
        client.post(
            reverse("catalog_vehicle_make_update", args=[make.pk]),
            {"name": "HondaUnique Updated"},
        )
        make.refresh_from_db()
        self.assertEqual(make.name, "HondaUnique Updated")

    def test_update_vehicle_model(self):
        make, _ = VehicleMake.objects.get_or_create(name="MazdaUnique")
        model = VehicleModel.objects.create(make=make, name="Old")
        client = self._client()
        client.post(
            reverse("catalog_vehicle_model_update", args=[model.pk]),
            {"make": str(make.pk), "name": "New"},
        )
        model.refresh_from_db()
        self.assertEqual(model.name, "New")
