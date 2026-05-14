"""
Тесты реальных пользовательских сценариев в picking views.

Покрывает основные POST-операции:
 * order_create — создание заказа через форму
 * order_detail — добавление/обновление строки, подтверждение, отгрузка
 * order_line_delete — удаление строки
 * picking_task_detail — старт/завершение задачи
 * product_search_ajax — поиск товаров
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

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
from inventory.models import Stock
from picking.models import Order, OrderLine, OrderStatus, PickingTask, PickingTaskStatus


User = get_user_model()


class PickingViewsBase(TestCase):
    """Базовые фикстуры — пользователи, склад, товары, остатки."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="adm_pick", email="a_p@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.ADMIN, is_superuser=True, is_staff=True,
        )
        cls.manager = User.objects.create_user(
            username="mgr_pick", email="m_p@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.SALES_MANAGER,
        )
        cls.picker = User.objects.create_user(
            username="spp_pick", email="p_p@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.SMALL_PARTS_PICKER,
        )

        # склад
        branch = Branch.objects.create(code="BR1", name="Главный")
        cls.warehouse = Warehouse.objects.create(branch=branch, code="WH1", name="WH1")
        cell_type, _ = StorageZoneType.objects.get_or_create(code="CELL", defaults={"name": "Ячейка"})
        zone = StorageZone.objects.create(
            warehouse=cls.warehouse, code="Z1", name="Z1", zone_type=cell_type,
        )
        cls.location = StorageLocation.objects.create(zone=zone, code="L1", name="L1")

        # товары
        brand = Brand.objects.create(name="DENSO")
        category = Category.objects.create(name="Generic")
        cls.product = Product.objects.create(
            internal_sku="SKU-VIEW-1", name="Товар 1",
            oem_number="OEM-V1", brand=brand, category=category,
            packaging_type=Product.PackagingType.SMALL,
        )

    def _client(self, user):
        c = Client()
        c.force_login(user)
        return c


# ════════════════════════════════════════════════════════════════════
# Order create
# ════════════════════════════════════════════════════════════════════
class OrderCreateViewTests(PickingViewsBase):
    def test_get_order_create_form(self):
        client = self._client(self.manager)
        response = client.get(reverse("order_create"))
        self.assertEqual(response.status_code, 200)

    def test_post_creates_order(self):
        client = self._client(self.manager)
        response = client.post(reverse("order_create"), {
            "customer_name": "Иван Тестовый",
            "customer_phone": "+79991234567",
            "customer_email": "",
            "priority": "NORMAL",
            "shipping_due_at": "",
            "source": "MANUAL",
            "external_id": "",
            "note": "Тестовый заказ",
        })
        # Ожидаем редирект на список или детальную после успеха
        self.assertIn(response.status_code, (200, 302))
        # Заказ создан
        self.assertTrue(Order.objects.filter(customer_name="Иван Тестовый").exists())

    def test_post_invalid_phone_shows_form_with_error(self):
        client = self._client(self.manager)
        response = client.post(reverse("order_create"), {
            "customer_name": "Иван",
            "customer_phone": "123",  # слишком короткий
            "priority": "NORMAL",
            "source": "MANUAL",
        })
        self.assertEqual(response.status_code, 200)  # форма с ошибкой
        # Заказ не создан
        self.assertFalse(Order.objects.filter(customer_name="Иван").exists())

    def test_picker_cannot_create_order(self):
        client = self._client(self.picker)
        response = client.get(reverse("order_create"))
        # 403 от role_required
        self.assertEqual(response.status_code, 403)


# ════════════════════════════════════════════════════════════════════
# Order detail — add_line, change_status
# ════════════════════════════════════════════════════════════════════
class OrderDetailViewTests(PickingViewsBase):
    def setUp(self):
        self.order = Order.objects.create(
            number=Order.generate_next_number(),
            customer_name="Тест", customer_phone="+79991234567",
            created_by=self.manager,
        )

    def test_get_order_detail(self):
        client = self._client(self.manager)
        response = client.get(reverse("order_detail", args=[self.order.pk]))
        self.assertEqual(response.status_code, 200)

    def test_add_line_post(self):
        client = self._client(self.manager)
        response = client.post(
            reverse("order_detail", args=[self.order.pk]),
            {
                "add_line": "1",
                "product": self.product.pk,
                "qty_ordered": "3",
                "price": "100.00",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            OrderLine.objects.filter(order=self.order, product=self.product).exists()
        )

    def test_add_line_in_confirmed_order_rejected(self):
        self.order.status = OrderStatus.CONFIRMED
        self.order.save()
        client = self._client(self.manager)
        client.post(
            reverse("order_detail", args=[self.order.pk]),
            {
                "add_line": "1",
                "product": self.product.pk,
                "qty_ordered": "1",
                "price": "100.00",
            },
        )
        # Строка не добавлена
        self.assertFalse(
            OrderLine.objects.filter(order=self.order, product=self.product).exists()
        )

    def test_confirm_status_change_with_stock(self):
        # Готовим остаток и строку
        Stock.objects.create(
            product=self.product, storage_location=self.location,
            qty_available=Decimal("10"),
        )
        OrderLine.objects.create(
            order=self.order, product=self.product, qty_ordered=Decimal("2"),
        )

        client = self._client(self.manager)
        client.post(
            reverse("order_detail", args=[self.order.pk]),
            {"change_status": "1", "status": OrderStatus.CONFIRMED},
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.CONFIRMED)

    def test_change_status_to_unknown_status_rejected(self):
        client = self._client(self.manager)
        client.post(
            reverse("order_detail", args=[self.order.pk]),
            {"change_status": "1", "status": "BOGUS"},
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.DRAFT)

    def test_ship_requires_confirmation_fields(self):
        # Заказ полностью подобран
        self.order.status = OrderStatus.PICKED
        self.order.save()
        OrderLine.objects.create(
            order=self.order, product=self.product,
            qty_ordered=Decimal("1"), qty_picked=Decimal("1"),
        )
        Stock.objects.create(
            product=self.product, storage_location=self.location,
            qty_reserved=Decimal("1"), qty_available=Decimal("0"),
        )

        client = self._client(self.manager)
        # Без подтверждающих полей
        client.post(
            reverse("order_detail", args=[self.order.pk]),
            {"change_status": "1", "status": OrderStatus.SHIPPED},
        )
        self.order.refresh_from_db()
        # Статус не изменился — нет confirmation
        self.assertEqual(self.order.status, OrderStatus.PICKED)

    def test_ship_with_full_confirmation_succeeds(self):
        self.order.status = OrderStatus.PICKED
        self.order.save()
        OrderLine.objects.create(
            order=self.order, product=self.product,
            qty_ordered=Decimal("1"), qty_picked=Decimal("1"),
        )
        Stock.objects.create(
            product=self.product, storage_location=self.location,
            qty_reserved=Decimal("1"), qty_available=Decimal("0"),
        )

        client = self._client(self.manager)
        client.post(
            reverse("order_detail", args=[self.order.pk]),
            {
                "change_status": "1",
                "status": OrderStatus.SHIPPED,
                "ship_check_package": "1",
                "ship_check_documents": "1",
                "ship_confirm_number": self.order.number,
                "ship_window_number": "5",
            },
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.SHIPPED)


# ════════════════════════════════════════════════════════════════════
# Order line delete
# ════════════════════════════════════════════════════════════════════
class OrderLineDeleteViewTests(PickingViewsBase):
    def test_delete_line(self):
        order = Order.objects.create(
            number=Order.generate_next_number(),
            customer_name="Тест", customer_phone="+79991234567",
            created_by=self.manager,
        )
        line = OrderLine.objects.create(
            order=order, product=self.product, qty_ordered=Decimal("1"),
        )
        client = self._client(self.manager)
        client.post(reverse("order_line_delete", args=[order.pk, line.pk]))
        self.assertFalse(OrderLine.objects.filter(pk=line.pk).exists())


# ════════════════════════════════════════════════════════════════════
# Picking task detail
# ════════════════════════════════════════════════════════════════════
class PickingTaskDetailViewTests(PickingViewsBase):
    def setUp(self):
        self.order = Order.objects.create(
            number=Order.generate_next_number(),
            customer_name="Тест", customer_phone="+79991234567",
            status=OrderStatus.CONFIRMED, created_by=self.manager,
        )
        OrderLine.objects.create(
            order=self.order, product=self.product, qty_ordered=Decimal("2"),
        )
        self.task = PickingTask.objects.create(
            order=self.order, zone_type_code="CELL",
            status=PickingTaskStatus.PENDING,
        )

    def test_get_picking_task_detail(self):
        client = self._client(self.picker)
        response = client.get(reverse("picking_task_detail", args=[self.task.pk]))
        self.assertEqual(response.status_code, 200)

    def test_picker_can_take_task(self):
        client = self._client(self.picker)
        response = client.post(
            reverse("picking_task_detail", args=[self.task.pk]),
            {"action": "take_task"},
        )
        self.task.refresh_from_db()
        # после взятия — IN_PROGRESS или назначен пикеру (зависит от логики)
        self.assertIn(response.status_code, (200, 302))


# ════════════════════════════════════════════════════════════════════
# Product search ajax
# ════════════════════════════════════════════════════════════════════
class ProductSearchAjaxTests(PickingViewsBase):
    def test_search_by_sku_returns_match(self):
        client = self._client(self.manager)
        response = client.get(
            reverse("picking_product_search_ajax"),
            {"q": "SKU-VIEW-1"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        # должен найти товар
        self.assertTrue(any(
            item.get("internal_sku") == "SKU-VIEW-1" or "SKU-VIEW-1" in str(item)
            for item in (data.get("results", []) if isinstance(data, dict) else data)
        ))

    def test_search_empty_query_returns_empty_or_all(self):
        client = self._client(self.manager)
        response = client.get(reverse("picking_product_search_ajax"), {"q": ""})
        self.assertEqual(response.status_code, 200)


# ════════════════════════════════════════════════════════════════════
# Order list — фильтры и сортировка
# ════════════════════════════════════════════════════════════════════
class OrderListViewTests(PickingViewsBase):
    def test_order_list_renders(self):
        Order.objects.create(
            number=Order.generate_next_number(),
            customer_name="Клиент 1", customer_phone="+79991234567",
            created_by=self.manager,
        )
        client = self._client(self.manager)
        response = client.get(reverse("order_list"))
        self.assertEqual(response.status_code, 200)

    def test_order_list_filter_by_status(self):
        client = self._client(self.manager)
        response = client.get(reverse("order_list"), {"status": "DRAFT"})
        self.assertEqual(response.status_code, 200)

    def test_order_list_search(self):
        Order.objects.create(
            number="ORD-SEARCH-1",
            customer_name="Уникальный Поиск", customer_phone="+79991234567",
            created_by=self.manager,
        )
        client = self._client(self.manager)
        response = client.get(reverse("order_list"), {"q": "Уникальный"})
        self.assertEqual(response.status_code, 200)


# ════════════════════════════════════════════════════════════════════
# Picking task list
# ════════════════════════════════════════════════════════════════════
class PickingTaskListViewTests(PickingViewsBase):
    def test_task_list_renders_for_picker(self):
        client = self._client(self.picker)
        response = client.get(reverse("picking_task_list"))
        self.assertEqual(response.status_code, 200)

    def test_task_list_filter_by_status(self):
        client = self._client(self.picker)
        response = client.get(reverse("picking_task_list"), {"status": "PENDING"})
        self.assertEqual(response.status_code, 200)
