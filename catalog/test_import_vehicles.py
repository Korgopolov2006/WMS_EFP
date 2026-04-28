"""
Тесты драйвера CarQuery и management-команды import_vehicles.
HTTP замоканы — реальный API не дёргается.
"""
import json
from io import StringIO
from unittest.mock import MagicMock

from django.core.management import call_command
from django.test import TestCase

from catalog.import_drivers.carquery import CarQueryDriver, _strip_jsonp
from catalog.models import VehicleMake, VehicleModel


class TestStripJsonp(TestCase):
    def test_strip_jsonp_wrapped(self):
        self.assertEqual(_strip_jsonp('?({"a":1});'), '{"a":1}')

    def test_strip_jsonp_no_wrap(self):
        self.assertEqual(_strip_jsonp('{"a":1}'), '{"a":1}')

    def test_strip_jsonp_empty(self):
        self.assertEqual(_strip_jsonp(''), '')


class _FakeResp:
    def __init__(self, text):
        self.text = text
    def raise_for_status(self): pass


def _make_client(responses):
    """responses: list[str] — отдаются по порядку при каждом get()."""
    client = MagicMock()
    iterator = iter(responses)
    client.get = MagicMock(side_effect=lambda *a, **kw: _FakeResp(next(iterator)))
    return client


class TestCarQueryDriver(TestCase):
    def _driver(self, responses):
        return CarQueryDriver(client=_make_client(responses), rate_limit_sec=0)

    def test_list_makes_returns_ids(self):
        payload = '?(' + json.dumps({"Makes": [
            {"make_id": "ford", "make_display": "Ford"},
            {"make_id": "bmw", "make_display": "BMW"},
        ]}) + ');'
        d = self._driver([payload])
        self.assertEqual(d.list_makes(), ["bmw", "ford"])

    def test_list_models(self):
        payload = '?(' + json.dumps({"Models": [
            {"model_name": "Mustang"},
            {"model_name": "Focus"},
            {"model_name": "Mustang"},  # дубль
        ]}) + ');'
        d = self._driver([payload])
        self.assertEqual(d.list_models("ford", 2020), ["Focus", "Mustang"])

    def test_iter_entries_yields_pairs(self):
        makes_payload = '?(' + json.dumps({"Makes": [
            {"make_id": "ford", "make_display": "Ford"},
        ]}) + ');'
        models_2020 = '?(' + json.dumps({"Models": [
            {"model_name": "Mustang"}, {"model_name": "Focus"}
        ]}) + ');'
        models_2021 = '?(' + json.dumps({"Models": [
            {"model_name": "Mustang"},  # дубль из прошлого года
            {"model_name": "Bronco"},
        ]}) + ');'
        d = self._driver([makes_payload, models_2020, models_2021])
        entries = list(d.iter_entries(year_from=2020, year_to=2021))
        names = sorted(e.model_name for e in entries)
        self.assertEqual(names, ["Bronco", "Focus", "Mustang"])
        self.assertTrue(all(e.make_name == "Ford" for e in entries))

    def test_iter_entries_filters_makes(self):
        makes_payload = '?(' + json.dumps({"Makes": [
            {"make_id": "ford", "make_display": "Ford"},
            {"make_id": "bmw", "make_display": "BMW"},
        ]}) + ');'
        models = '?(' + json.dumps({"Models": [{"model_name": "X5"}]}) + ');'
        d = self._driver([makes_payload, models])
        entries = list(d.iter_entries(year_from=2020, year_to=2020, makes=["bmw"]))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].make_name, "BMW")
        self.assertEqual(entries[0].model_name, "X5")


class _FakeDriver:
    name = "fake"
    def iter_entries(self, *, year_from, year_to, makes=None):
        from catalog.import_drivers.base import VehicleEntry
        # Используем уникальные тестовые названия чтобы не пересекаться с seed
        yield VehicleEntry(make_name="TestMake-A", model_name="TestModel-1")
        yield VehicleEntry(make_name="TestMake-A", model_name="TestModel-2")
        yield VehicleEntry(make_name="TestMake-B", model_name="TestModel-3")


class TestImportCommand(TestCase):
    """Патчим get_driver внутри модуля команды."""

    def _run(self, *args):
        from unittest.mock import patch
        out = StringIO()
        with patch(
            "catalog.management.commands.import_vehicles.get_driver_for_command",
            return_value=_FakeDriver(),
        ):
            call_command("import_vehicles", *args, stdout=out)
        return out.getvalue()

    def test_command_creates_records(self):
        out = self._run("--year-from", "2020", "--year-to", "2020")
        self.assertEqual(VehicleMake.objects.filter(name__in=["TestMake-A", "TestMake-B"]).count(), 2)
        self.assertTrue(VehicleModel.objects.filter(make__name="TestMake-A", name="TestModel-1").exists())
        self.assertIn("Готово", out)

    def test_command_dry_run_does_not_write(self):
        before_makes = VehicleMake.objects.count()
        before_models = VehicleModel.objects.count()
        self._run("--year-from", "2020", "--year-to", "2020", "--dry-run")
        self.assertEqual(VehicleMake.objects.count(), before_makes)
        self.assertEqual(VehicleModel.objects.count(), before_models)

    def test_command_idempotent(self):
        self._run("--year-from", "2020", "--year-to", "2020")
        first = VehicleModel.objects.filter(make__name__startswith="TestMake-").count()
        self._run("--year-from", "2020", "--year-to", "2020")
        self.assertEqual(
            VehicleModel.objects.filter(make__name__startswith="TestMake-").count(),
            first,
        )

    def test_command_limit(self):
        self._run("--limit", "2", "--year-from", "2020", "--year-to", "2020")
        # Должно быть ровно 2 модели из тестовых; третья (TestMake-B) не должна попасть
        self.assertEqual(
            VehicleModel.objects.filter(make__name__startswith="TestMake-").count(),
            2,
        )
        self.assertFalse(VehicleModel.objects.filter(make__name="TestMake-B").exists())
