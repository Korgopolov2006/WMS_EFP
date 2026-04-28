"""
Интеграционные тесты WMS-разделов административной панели.
Покрывает: склады (CRUD), поставщики (CRUD), товары, заказы, остатки, приёмки, задачи.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


# ─────────────────────────────────────────────────────────────
#  Фикстуры
# ─────────────────────────────────────────────────────────────

def make_admin(**kw) -> User:
    d = dict(username="wms_admin", email="wms_admin@test.ru",
             password="AdminPass1!XYZW", role="ADMIN", is_active=True)
    d.update(kw)
    return User.objects.create_user(**d)


def make_user(**kw) -> User:
    d = dict(username="wms_user", email="wms_user@test.ru",
             password="UserPass1!XYZWAB", role="STOREKEEPER", is_active=True)
    d.update(kw)
    return User.objects.create_user(**d)


def make_branch(code="TEST", name="Тестовый филиал"):
    from catalog.models import Branch
    return Branch.objects.create(code=code, name=name)


def make_warehouse(branch, code="WH01", name="Тестовый склад"):
    from catalog.models import Warehouse
    return Warehouse.objects.create(branch=branch, code=code, name=name)


def make_supplier(code="SUP01", name="Тестовый поставщик"):
    from receiving.models import Supplier
    return Supplier.objects.create(code=code, name=name)


# ═════════════════════════════════════════════════════════════
#  Склады
# ═════════════════════════════════════════════════════════════

class TestWarehouseList(TestCase):

    def setUp(self):
        self.admin = make_admin()
        self.client.force_login(self.admin)
        self.branch = make_branch()
        make_warehouse(self.branch, code="W1", name="Склад 1")
        make_warehouse(self.branch, code="W2", name="Склад 2")

    def test_list_renders_200(self):
        resp = self.client.get(reverse("admin_panel:wms_warehouse_list"))
        self.assertEqual(resp.status_code, 200)

    def test_list_shows_warehouses(self):
        resp = self.client.get(reverse("admin_panel:wms_warehouse_list"))
        self.assertContains(resp, "Склад 1")
        self.assertContains(resp, "Склад 2")

    def test_search_filters(self):
        resp = self.client.get(reverse("admin_panel:wms_warehouse_list"), {"q": "Склад 1"})
        self.assertContains(resp, "Склад 1")
        self.assertNotContains(resp, "Склад 2")

    def test_status_filter_active(self):
        resp = self.client.get(reverse("admin_panel:wms_warehouse_list"), {"status": "active"})
        self.assertEqual(resp.status_code, 200)

    def test_branch_filter(self):
        resp = self.client.get(
            reverse("admin_panel:wms_warehouse_list"),
            {"branch": str(self.branch.pk)},
        )
        self.assertContains(resp, "Склад 1")

    def test_non_admin_denied(self):
        user = make_user(username="whs_nonadmin", email="whs_nonadmin@test.ru")
        self.client.force_login(user)
        resp = self.client.get(reverse("admin_panel:wms_warehouse_list"))
        self.assertEqual(resp.status_code, 403)

    def test_anonymous_redirected(self):
        self.client.logout()
        resp = self.client.get(reverse("admin_panel:wms_warehouse_list"))
        self.assertEqual(resp.status_code, 302)


class TestWarehouseCreate(TestCase):

    def setUp(self):
        self.admin = make_admin(username="wh_create_admin", email="whca@test.ru")
        self.client.force_login(self.admin)
        self.branch = make_branch(code="BC1", name="Создание")

    def test_get_renders_form(self):
        resp = self.client.get(reverse("admin_panel:wms_warehouse_create"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Создать склад")

    def test_post_creates_warehouse(self):
        resp = self.client.post(reverse("admin_panel:wms_warehouse_create"), {
            "branch": self.branch.pk,
            "code": "NEW01",
            "name": "Новый склад",
            "width_m": "30.0",
            "length_m": "40.0",
            "height_m": "8.0",
            "is_active": True,
        })
        self.assertRedirects(resp, reverse("admin_panel:wms_warehouse_list"),
                              fetch_redirect_response=False)
        from catalog.models import Warehouse
        self.assertTrue(Warehouse.objects.filter(code="NEW01").exists())

    def test_duplicate_code_in_same_branch_shows_error(self):
        make_warehouse(self.branch, code="DUPE", name="Дубликат")
        resp = self.client.post(reverse("admin_panel:wms_warehouse_create"), {
            "branch": self.branch.pk,
            "code": "DUPE",
            "name": "Другой склад",
            "width_m": "30.0",
            "length_m": "40.0",
            "height_m": "8.0",
            "is_active": True,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "уже существует")

    def test_post_creates_audit_log(self):
        from admin_panel.models import AuditLog
        self.client.post(reverse("admin_panel:wms_warehouse_create"), {
            "branch": self.branch.pk,
            "code": "AUDIT01",
            "name": "Аудит склад",
            "width_m": "10.0",
            "length_m": "10.0",
            "height_m": "5.0",
            "is_active": True,
        })
        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.ActionType.CREATE,
                resource_type="Warehouse",
            ).exists()
        )


class TestWarehouseEdit(TestCase):

    def setUp(self):
        self.admin = make_admin(username="wh_edit_admin", email="whea@test.ru")
        self.client.force_login(self.admin)
        self.branch = make_branch(code="BE1", name="Редактирование")
        self.wh = make_warehouse(self.branch, code="EDIT01", name="Старое имя")

    def test_get_renders_form(self):
        resp = self.client.get(reverse("admin_panel:wms_warehouse_edit", args=[self.wh.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Старое имя")

    def test_post_updates_name(self):
        resp = self.client.post(
            reverse("admin_panel:wms_warehouse_edit", args=[self.wh.pk]),
            {
                "branch": self.branch.pk,
                "code": "EDIT01",
                "name": "Новое имя",
                "width_m": "30.0",
                "length_m": "40.0",
                "height_m": "8.0",
                "is_active": True,
            },
        )
        self.assertRedirects(resp, reverse("admin_panel:wms_warehouse_list"),
                              fetch_redirect_response=False)
        self.wh.refresh_from_db()
        self.assertEqual(self.wh.name, "Новое имя")

    def test_creates_audit_log_on_update(self):
        from admin_panel.models import AuditLog
        self.client.post(
            reverse("admin_panel:wms_warehouse_edit", args=[self.wh.pk]),
            {
                "branch": self.branch.pk,
                "code": "EDIT01",
                "name": "Обновлённое имя",
                "width_m": "30.0",
                "length_m": "40.0",
                "height_m": "8.0",
                "is_active": False,
            },
        )
        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.ActionType.UPDATE,
                resource_type="Warehouse",
                resource_id=str(self.wh.pk),
            ).exists()
        )


class TestWarehouseDelete(TestCase):

    def setUp(self):
        self.admin = make_admin(username="wh_del_admin", email="whda@test.ru")
        self.client.force_login(self.admin)
        self.branch = make_branch(code="BD1", name="Удаление")
        self.wh = make_warehouse(self.branch, code="DEL01", name="На удаление")

    def test_get_shows_confirm_page(self):
        resp = self.client.get(reverse("admin_panel:wms_warehouse_delete", args=[self.wh.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "На удаление")

    def test_post_deletes_warehouse(self):
        pk = self.wh.pk
        resp = self.client.post(reverse("admin_panel:wms_warehouse_delete", args=[pk]))
        self.assertRedirects(resp, reverse("admin_panel:wms_warehouse_list"),
                              fetch_redirect_response=False)
        from catalog.models import Warehouse
        self.assertFalse(Warehouse.objects.filter(pk=pk).exists())

    def test_delete_creates_audit_log(self):
        from admin_panel.models import AuditLog
        pk = self.wh.pk
        self.client.post(reverse("admin_panel:wms_warehouse_delete", args=[pk]))
        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.ActionType.DELETE,
                resource_type="Warehouse",
                resource_id=str(pk),
            ).exists()
        )


# ═════════════════════════════════════════════════════════════
#  Поставщики
# ═════════════════════════════════════════════════════════════

class TestSupplierList(TestCase):

    def setUp(self):
        self.admin = make_admin(username="sup_list_admin", email="sla@test.ru")
        self.client.force_login(self.admin)
        make_supplier(code="A001", name="Поставщик Альфа")
        make_supplier(code="B002", name="Поставщик Бета")

    def test_list_renders_200(self):
        resp = self.client.get(reverse("admin_panel:wms_supplier_list"))
        self.assertEqual(resp.status_code, 200)

    def test_shows_suppliers(self):
        resp = self.client.get(reverse("admin_panel:wms_supplier_list"))
        self.assertContains(resp, "Поставщик Альфа")
        self.assertContains(resp, "Поставщик Бета")

    def test_search_by_name(self):
        resp = self.client.get(reverse("admin_panel:wms_supplier_list"), {"q": "Альфа"})
        self.assertContains(resp, "Поставщик Альфа")
        self.assertNotContains(resp, "Поставщик Бета")

    def test_filter_active(self):
        resp = self.client.get(reverse("admin_panel:wms_supplier_list"), {"status": "active"})
        self.assertEqual(resp.status_code, 200)

    def test_non_admin_denied(self):
        user = make_user(username="sup_nonadmin", email="sup_nonadmin@test.ru")
        self.client.force_login(user)
        resp = self.client.get(reverse("admin_panel:wms_supplier_list"))
        self.assertEqual(resp.status_code, 403)


class TestSupplierCreate(TestCase):

    def setUp(self):
        self.admin = make_admin(username="sup_create_admin", email="sca@test.ru")
        self.client.force_login(self.admin)

    def test_get_renders_form(self):
        resp = self.client.get(reverse("admin_panel:wms_supplier_create"))
        self.assertEqual(resp.status_code, 200)

    def test_post_creates_supplier(self):
        resp = self.client.post(reverse("admin_panel:wms_supplier_create"), {
            "code": "NEW01",
            "name": "Новый поставщик",
            "is_active": True,
        })
        self.assertRedirects(resp, reverse("admin_panel:wms_supplier_list"),
                              fetch_redirect_response=False)
        from receiving.models import Supplier
        self.assertTrue(Supplier.objects.filter(code="NEW01").exists())

    def test_duplicate_code_shows_error(self):
        make_supplier(code="DUPE", name="Дубликат поставщик")
        resp = self.client.post(reverse("admin_panel:wms_supplier_create"), {
            "code": "dupe",   # lowercase — должен нормализоваться в uppercase и выдать ошибку
            "name": "Другой поставщик",
            "is_active": True,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "уже существует")

    def test_post_creates_audit_log(self):
        from admin_panel.models import AuditLog
        self.client.post(reverse("admin_panel:wms_supplier_create"), {
            "code": "AUDIT02",
            "name": "Аудит поставщик",
            "is_active": True,
        })
        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.ActionType.CREATE,
                resource_type="Supplier",
            ).exists()
        )


class TestSupplierEdit(TestCase):

    def setUp(self):
        self.admin = make_admin(username="sup_edit_admin", email="sea@test.ru")
        self.client.force_login(self.admin)
        self.supplier = make_supplier(code="EDIT02", name="Старое название")

    def test_get_renders_form(self):
        resp = self.client.get(reverse("admin_panel:wms_supplier_edit", args=[self.supplier.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Старое название")

    def test_post_updates_name(self):
        resp = self.client.post(
            reverse("admin_panel:wms_supplier_edit", args=[self.supplier.pk]),
            {"code": "EDIT02", "name": "Новое название", "is_active": True},
        )
        self.assertRedirects(resp, reverse("admin_panel:wms_supplier_list"),
                              fetch_redirect_response=False)
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.name, "Новое название")


class TestSupplierToggleActive(TestCase):

    def setUp(self):
        self.admin = make_admin(username="sup_toggle_admin", email="sta@test.ru")
        self.client.force_login(self.admin)
        self.supplier = make_supplier(code="TOG01", name="Переключаемый")

    def test_toggle_deactivates(self):
        self.assertTrue(self.supplier.is_active)
        self.client.post(reverse("admin_panel:wms_supplier_toggle", args=[self.supplier.pk]))
        self.supplier.refresh_from_db()
        self.assertFalse(self.supplier.is_active)

    def test_toggle_activates(self):
        self.supplier.is_active = False
        self.supplier.save()
        self.client.post(reverse("admin_panel:wms_supplier_toggle", args=[self.supplier.pk]))
        self.supplier.refresh_from_db()
        self.assertTrue(self.supplier.is_active)

    def test_get_not_allowed(self):
        resp = self.client.get(
            reverse("admin_panel:wms_supplier_toggle", args=[self.supplier.pk])
        )
        self.assertEqual(resp.status_code, 405)

    def test_creates_audit_log(self):
        from admin_panel.models import AuditLog
        self.client.post(reverse("admin_panel:wms_supplier_toggle", args=[self.supplier.pk]))
        self.assertTrue(
            AuditLog.objects.filter(
                action__in=[AuditLog.ActionType.ACTIVATE, AuditLog.ActionType.DEACTIVATE],
                resource_type="Supplier",
                resource_id=str(self.supplier.pk),
            ).exists()
        )


class TestSupplierDelete(TestCase):

    def setUp(self):
        self.admin = make_admin(username="sup_del_admin", email="sda@test.ru")
        self.client.force_login(self.admin)
        self.supplier = make_supplier(code="DEL02", name="На удаление")

    def test_get_shows_confirm(self):
        resp = self.client.get(reverse("admin_panel:wms_supplier_delete", args=[self.supplier.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "На удаление")

    def test_post_deletes_supplier(self):
        pk = self.supplier.pk
        resp = self.client.post(reverse("admin_panel:wms_supplier_delete", args=[pk]))
        self.assertRedirects(resp, reverse("admin_panel:wms_supplier_list"),
                              fetch_redirect_response=False)
        from receiving.models import Supplier
        self.assertFalse(Supplier.objects.filter(pk=pk).exists())


# ═════════════════════════════════════════════════════════════
#  Обзорные разделы (только GET / 200)
# ═════════════════════════════════════════════════════════════

class TestWmsReadonlyViews(TestCase):
    """Проверяет, что все обзорные страницы WMS рендерятся без ошибок."""

    def setUp(self):
        self.admin = make_admin(username="ro_admin", email="ro_admin@test.ru")
        self.client.force_login(self.admin)

    def test_product_list_renders(self):
        resp = self.client.get(reverse("admin_panel:wms_product_list"))
        self.assertEqual(resp.status_code, 200)

    def test_order_list_renders(self):
        resp = self.client.get(reverse("admin_panel:wms_order_list"))
        self.assertEqual(resp.status_code, 200)

    def test_stock_list_renders(self):
        resp = self.client.get(reverse("admin_panel:wms_stock_list"))
        self.assertEqual(resp.status_code, 200)

    def test_receiving_list_renders(self):
        resp = self.client.get(reverse("admin_panel:wms_receiving_list"))
        self.assertEqual(resp.status_code, 200)

    def test_task_list_renders(self):
        resp = self.client.get(reverse("admin_panel:wms_task_list"))
        self.assertEqual(resp.status_code, 200)

    def test_product_list_search(self):
        resp = self.client.get(reverse("admin_panel:wms_product_list"), {"q": "Тест"})
        self.assertEqual(resp.status_code, 200)

    def test_order_list_status_filter(self):
        resp = self.client.get(reverse("admin_panel:wms_order_list"), {"status": "DRAFT"})
        self.assertEqual(resp.status_code, 200)

    def test_receiving_list_status_filter(self):
        resp = self.client.get(reverse("admin_panel:wms_receiving_list"), {"status": "DRAFT"})
        self.assertEqual(resp.status_code, 200)

    def test_task_list_type_filter(self):
        resp = self.client.get(reverse("admin_panel:wms_task_list"), {"task_type": "RECEIVING"})
        self.assertEqual(resp.status_code, 200)

    def test_task_list_priority_filter(self):
        resp = self.client.get(reverse("admin_panel:wms_task_list"), {"priority": "HIGH"})
        self.assertEqual(resp.status_code, 200)

    def test_task_list_combined_filters(self):
        resp = self.client.get(reverse("admin_panel:wms_task_list"), {
            "status": "PENDING", "priority": "NORMAL", "task_type": "OTHER",
        })
        self.assertEqual(resp.status_code, 200)

    def test_non_admin_denied_on_product_list(self):
        user = make_user(username="ro_nonadmin", email="ro_nonadmin@test.ru")
        self.client.force_login(user)
        resp = self.client.get(reverse("admin_panel:wms_product_list"))
        self.assertEqual(resp.status_code, 403)


# ═════════════════════════════════════════════════════════════
#  Формы (WarehouseForm, SupplierForm)
# ═════════════════════════════════════════════════════════════

class TestWarehouseForm(TestCase):

    def setUp(self):
        self.branch = make_branch(code="FRM", name="Форма тест")

    def test_valid_form(self):
        from admin_panel.forms import WarehouseForm
        form = WarehouseForm(data={
            "branch": self.branch.pk,
            "code": "FRM01",
            "name": "Тест склад",
            "width_m": "30.0",
            "length_m": "40.0",
            "height_m": "8.0",
            "is_active": True,
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_missing_code_invalid(self):
        from admin_panel.forms import WarehouseForm
        form = WarehouseForm(data={
            "branch": self.branch.pk,
            "code": "",
            "name": "Без кода",
            "width_m": "30.0",
            "length_m": "40.0",
            "height_m": "8.0",
            "is_active": True,
        })
        self.assertFalse(form.is_valid())
        self.assertIn("code", form.errors)

    def test_duplicate_code_same_branch(self):
        from admin_panel.forms import WarehouseForm
        make_warehouse(self.branch, code="DUP01", name="Существующий")
        form = WarehouseForm(data={
            "branch": self.branch.pk,
            "code": "DUP01",
            "name": "Другой",
            "width_m": "10.0",
            "length_m": "10.0",
            "height_m": "5.0",
            "is_active": True,
        })
        self.assertFalse(form.is_valid())
        self.assertIn("code", form.errors)


class TestSupplierForm(TestCase):

    def test_valid_form(self):
        from admin_panel.forms import SupplierForm
        form = SupplierForm(data={"code": "TST01", "name": "Тест поставщик", "is_active": True})
        self.assertTrue(form.is_valid(), form.errors)

    def test_code_uppercased(self):
        from admin_panel.forms import SupplierForm
        form = SupplierForm(data={"code": "tst02", "name": "Нижний регистр", "is_active": True})
        form.is_valid()
        self.assertEqual(form.cleaned_data.get("code"), "TST02")

    def test_duplicate_code(self):
        from admin_panel.forms import SupplierForm
        make_supplier(code="DUPE99", name="Существующий поставщик")
        form = SupplierForm(data={"code": "DUPE99", "name": "Новый", "is_active": True})
        self.assertFalse(form.is_valid())
        self.assertIn("code", form.errors)

    def test_duplicate_name(self):
        from admin_panel.forms import SupplierForm
        make_supplier(code="X001", name="Уникальное название")
        form = SupplierForm(data={"code": "X002", "name": "Уникальное название", "is_active": True})
        self.assertFalse(form.is_valid())
        self.assertIn("name", form.errors)

    def test_missing_name(self):
        from admin_panel.forms import SupplierForm
        form = SupplierForm(data={"code": "X003", "name": "", "is_active": True})
        self.assertFalse(form.is_valid())
        self.assertIn("name", form.errors)


# ═════════════════════════════════════════════════════════════
#  Дополнительные тесты для 100% покрытия views.py
# ═════════════════════════════════════════════════════════════

class TestWarehouseListInactiveFilter(TestCase):
    """Строка 499: status_filter == 'inactive' в wms_warehouse_list."""

    def setUp(self):
        self.admin = make_admin(username="wh_inactive_admin", email="whin@test.ru")
        self.client.force_login(self.admin)
        branch = make_branch(code="INB", name="Инактивная ветка")
        from catalog.models import Warehouse
        Warehouse.objects.create(branch=branch, code="ACT", name="Активный склад", is_active=True)
        Warehouse.objects.create(branch=branch, code="INA", name="Неактивный склад", is_active=False)

    def test_inactive_status_filter(self):
        resp = self.client.get(
            reverse("admin_panel:wms_warehouse_list"), {"status": "inactive"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Неактивный склад")
        self.assertNotContains(resp, "Активный склад")


class TestWarehouseDeleteException(TestCase):
    """Строки 587-588: exception при удалении склада (PROTECT)."""

    def setUp(self):
        self.admin = make_admin(username="wh_del_exc_admin", email="whdex@test.ru")
        self.client.force_login(self.admin)
        branch = make_branch(code="EXB", name="Exception Branch")
        self.wh = make_warehouse(branch, code="PROT", name="Защищённый склад")

    def test_delete_raises_on_protected_relations(self):
        """Если склад защищён (ProtectedError), вью должна показать ошибку и перенаправить."""
        from unittest.mock import patch
        with patch("admin_panel.views.wms_warehouse_delete.__wrapped__",
                   side_effect=None):
            # Имитируем ошибку через патч модели
            with patch.object(
                self.wh.__class__,
                "delete",
                side_effect=Exception("Cannot delete: PROTECT"),
            ):
                resp = self.client.post(
                    reverse("admin_panel:wms_warehouse_delete", args=[self.wh.pk])
                )
        self.assertRedirects(resp, reverse("admin_panel:wms_warehouse_list"),
                              fetch_redirect_response=False)


class TestSupplierListInactiveFilter(TestCase):
    """Строка 613: status_filter == 'inactive' в wms_supplier_list."""

    def setUp(self):
        self.admin = make_admin(username="sup_inactive_admin", email="supina@test.ru")
        self.client.force_login(self.admin)
        make_supplier(code="ACTSUP", name="Активный поставщик")
        from receiving.models import Supplier
        Supplier.objects.create(code="INASUP", name="Неактивный поставщик", is_active=False)

    def test_inactive_status_filter(self):
        resp = self.client.get(
            reverse("admin_panel:wms_supplier_list"), {"status": "inactive"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Неактивный поставщик")
        self.assertNotContains(resp, "Активный поставщик")


class TestSupplierDeleteException(TestCase):
    """Строки 711-712: exception при удалении поставщика (PROTECT)."""

    def setUp(self):
        self.admin = make_admin(username="sup_del_exc_admin", email="spdex@test.ru")
        self.client.force_login(self.admin)
        self.supplier = make_supplier(code="PROTSUP", name="Защищённый поставщик")

    def test_delete_raises_redirects_with_error(self):
        from unittest.mock import patch
        with patch.object(
            self.supplier.__class__,
            "delete",
            side_effect=Exception("PROTECT violation"),
        ):
            resp = self.client.post(
                reverse("admin_panel:wms_supplier_delete", args=[self.supplier.pk])
            )
        self.assertRedirects(resp, reverse("admin_panel:wms_supplier_list"),
                              fetch_redirect_response=False)


class TestProductListFilters(TestCase):
    """Строки 740, 742: brand_filter и category_filter в wms_product_list."""

    def setUp(self):
        self.admin = make_admin(username="prod_filter_admin", email="pfa@test.ru")
        self.client.force_login(self.admin)
        from catalog.models import Brand, Category
        self.brand = Brand.objects.create(name="Тест бренд 999")
        self.category = Category.objects.create(name="Тест категория 999")

    def test_brand_filter(self):
        resp = self.client.get(
            reverse("admin_panel:wms_product_list"),
            {"brand": str(self.brand.pk)},
        )
        self.assertEqual(resp.status_code, 200)

    def test_category_filter(self):
        resp = self.client.get(
            reverse("admin_panel:wms_product_list"),
            {"category": str(self.category.pk)},
        )
        self.assertEqual(resp.status_code, 200)

    def test_brand_and_category_filter(self):
        resp = self.client.get(
            reverse("admin_panel:wms_product_list"),
            {"brand": str(self.brand.pk), "category": str(self.category.pk)},
        )
        self.assertEqual(resp.status_code, 200)


class TestWmsSearchFilters(TestCase):
    """
    Строки 772, 802, 830, 860 — поисковые q-фильтры в обзорных разделах
    требуют непустой строки для входа в ветку if q.
    """

    def setUp(self):
        self.admin = make_admin(username="srch_admin", email="srch_admin@test.ru")
        self.client.force_login(self.admin)

    def test_order_search_with_q(self):
        resp = self.client.get(
            reverse("admin_panel:wms_order_list"), {"q": "ORD-"}
        )
        self.assertEqual(resp.status_code, 200)

    def test_stock_search_with_q(self):
        resp = self.client.get(
            reverse("admin_panel:wms_stock_list"), {"q": "SKU-"}
        )
        self.assertEqual(resp.status_code, 200)

    def test_receiving_search_with_q(self):
        resp = self.client.get(
            reverse("admin_panel:wms_receiving_list"), {"q": "RCV-"}
        )
        self.assertEqual(resp.status_code, 200)

    def test_task_search_with_q(self):
        resp = self.client.get(
            reverse("admin_panel:wms_task_list"), {"q": "приёмка"}
        )
        self.assertEqual(resp.status_code, 200)
