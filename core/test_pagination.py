"""
Юнит-тесты core/pagination.py.

Тесты не требуют БД и не открывают браузер — простой проверкой
функций показывают что:
  • per_page читается из GET-параметра;
  • невалидные/отсутствующие значения дают default;
  • paginate() корректно возвращает (page_obj, per_page).
"""
from __future__ import annotations

from django.test import RequestFactory, SimpleTestCase

from core.pagination import (
    ALLOWED_PER_PAGE,
    DEFAULT_PER_PAGE,
    get_per_page,
    paginate,
    paginate_legacy,
)


class GetPerPageTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_returns_default_when_not_provided(self):
        req = self.factory.get("/")
        self.assertEqual(get_per_page(req), DEFAULT_PER_PAGE)

    def test_returns_default_when_empty(self):
        req = self.factory.get("/", {"per_page": ""})
        self.assertEqual(get_per_page(req), DEFAULT_PER_PAGE)

    def test_returns_default_when_not_int(self):
        req = self.factory.get("/", {"per_page": "abc"})
        self.assertEqual(get_per_page(req), DEFAULT_PER_PAGE)

    def test_returns_default_when_not_allowed(self):
        req = self.factory.get("/", {"per_page": "7"})  # не в ALLOWED
        self.assertEqual(get_per_page(req), DEFAULT_PER_PAGE)

    def test_returns_allowed_value(self):
        for value in ALLOWED_PER_PAGE:
            req = self.factory.get("/", {"per_page": str(value)})
            self.assertEqual(get_per_page(req), value)

    def test_custom_default(self):
        req = self.factory.get("/")
        self.assertEqual(get_per_page(req, default=50), 50)

    def test_custom_param_name(self):
        req = self.factory.get("/", {"size": "25"})
        self.assertEqual(get_per_page(req, param="size"), 25)


class PaginateTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.items = list(range(1, 101))  # 100 элементов

    def test_returns_default_page_size(self):
        req = self.factory.get("/")
        page_obj, per_page = paginate(self.items, req) if False else paginate(req, self.items)
        self.assertEqual(per_page, DEFAULT_PER_PAGE)
        self.assertEqual(len(page_obj.object_list), DEFAULT_PER_PAGE)

    def test_custom_per_page_from_get(self):
        req = self.factory.get("/", {"per_page": "25"})
        page_obj, per_page = paginate(req, self.items)
        self.assertEqual(per_page, 25)
        self.assertEqual(len(page_obj.object_list), 25)

    def test_custom_page_number(self):
        req = self.factory.get("/", {"per_page": "10", "page": "3"})
        page_obj, _ = paginate(req, self.items)
        self.assertEqual(page_obj.number, 3)
        # На странице 3 при per_page=10 — элементы 21..30
        self.assertEqual(page_obj.object_list[0], 21)

    def test_invalid_per_page_falls_back(self):
        req = self.factory.get("/", {"per_page": "abc"})
        _, per_page = paginate(req, self.items)
        self.assertEqual(per_page, DEFAULT_PER_PAGE)

    def test_per_page_outside_allowed_uses_default(self):
        req = self.factory.get("/", {"per_page": "999"})
        _, per_page = paginate(req, self.items)
        self.assertEqual(per_page, DEFAULT_PER_PAGE)

    def test_empty_list(self):
        req = self.factory.get("/")
        page_obj, _ = paginate(req, [])
        self.assertEqual(page_obj.paginator.count, 0)


class PaginateLegacyTests(SimpleTestCase):
    """Обратная совместимость со старой сигнатурой `_paginate`."""

    def setUp(self):
        self.factory = RequestFactory()

    def test_returns_only_page_obj(self):
        req = self.factory.get("/")
        result = paginate_legacy(req, list(range(50)), per_page=10)
        # Не кортеж — только page_obj
        self.assertTrue(hasattr(result, "object_list"))
        self.assertEqual(len(result.object_list), 10)

    def test_user_per_page_overrides_default(self):
        req = self.factory.get("/", {"per_page": "25"})
        result = paginate_legacy(req, list(range(50)), per_page=10)
        # Пользовательский per_page=25 переопределяет default=10
        self.assertEqual(len(result.object_list), 25)

    def test_custom_page_param(self):
        req = self.factory.get("/", {"wh_page": "2"})
        result = paginate_legacy(
            req, list(range(50)), per_page=10, page_param="wh_page",
        )
        self.assertEqual(result.number, 2)
