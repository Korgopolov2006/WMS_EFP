"""
Драйвер-генератор реалистичных запчастей.

Зачем:
  • TecDoc/Laximo — платные.
  • Бесплатных API с реальными OEM/именами запчастей с возможностью
    коммерческого использования практически нет.
  • Для диплома и демо нужен наполненный каталог с правдоподобными данными:
    бренд, категория, OEM-номер, применимость к моделям ТС.

Что делает:
  • На основе импортированных VehicleMake/VehicleModel генерирует Product'ы
    по конфигурируемым шаблонам категорий запчастей (масла, колодки, фильтры…).
  • OEM-номера — детерминированные (хеш + бренд-префикс + категория-префикс)
    → повторный прогон не плодит дубликаты.
  • Применимость заполняется через каждую вторую модель производителя
    (имитирует реальную «семейность» запчастей).
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable

from .base import PartCategoryEntry, PartEntry, PartsImportDriver

# ── Каталог категорий с типичными атрибутами ────────────────
#  (name, parent, brand_pool, sku_prefix, weight_kg)
PART_CATEGORIES: tuple[dict, ...] = (
    {"name": "Двигатель", "parent": "", "children": [
        {"name": "Масляный фильтр",       "brands": ["Mann", "Bosch", "Mahle", "Filtron"],   "sku": "OIL", "weight": 0.3},
        {"name": "Воздушный фильтр",      "brands": ["Mann", "Bosch", "Mahle", "Filtron"],   "sku": "AIR", "weight": 0.4},
        {"name": "Топливный фильтр",      "brands": ["Mann", "Bosch", "Mahle"],              "sku": "FUE", "weight": 0.3},
        {"name": "Свеча зажигания",       "brands": ["NGK", "Denso", "Bosch", "Champion"],   "sku": "SPK", "weight": 0.05},
        {"name": "Ремень ГРМ",            "brands": ["Gates", "ContiTech", "Bosch", "Dayco"], "sku": "TIM", "weight": 0.5},
        {"name": "Натяжитель ремня",      "brands": ["INA", "SKF", "Gates", "ContiTech"],    "sku": "TEN", "weight": 0.6},
        {"name": "Ремень генератора",     "brands": ["Gates", "ContiTech", "Bosch"],         "sku": "ALT", "weight": 0.3},
    ]},
    {"name": "Тормозная система", "parent": "", "children": [
        {"name": "Тормозные колодки",     "brands": ["Brembo", "TRW", "Bosch", "Ferodo"],    "sku": "BPD", "weight": 1.5},
        {"name": "Тормозные диски",       "brands": ["Brembo", "TRW", "Bosch", "Zimmermann"], "sku": "BDS", "weight": 6.0},
        {"name": "Тормозной шланг",       "brands": ["TRW", "ATE", "Brembo"],                "sku": "BHO", "weight": 0.4},
        {"name": "Тормозная жидкость",    "brands": ["Castrol", "Liqui Moly", "Bosch"],      "sku": "BFL", "weight": 1.0},
    ]},
    {"name": "Подвеска", "parent": "", "children": [
        {"name": "Амортизатор передний",  "brands": ["Sachs", "Monroe", "Bilstein", "KYB"],  "sku": "SHF", "weight": 3.5},
        {"name": "Амортизатор задний",    "brands": ["Sachs", "Monroe", "Bilstein", "KYB"],  "sku": "SHR", "weight": 3.0},
        {"name": "Пружина подвески",      "brands": ["Lesjofors", "Sachs", "KYB"],           "sku": "SPR", "weight": 2.5},
        {"name": "Сайлентблок",           "brands": ["Lemforder", "Febi", "TRW"],            "sku": "BUS", "weight": 0.4},
        {"name": "Шаровая опора",         "brands": ["Lemforder", "TRW", "Moog"],            "sku": "BJT", "weight": 0.7},
        {"name": "Стойка стабилизатора",  "brands": ["Lemforder", "Febi", "TRW"],            "sku": "STB", "weight": 0.5},
    ]},
    {"name": "Электрика", "parent": "", "children": [
        {"name": "Аккумулятор",           "brands": ["Bosch", "Varta", "Exide", "Mutlu"],    "sku": "BAT", "weight": 18.0},
        {"name": "Стартер",               "brands": ["Bosch", "Valeo", "Denso"],             "sku": "STR", "weight": 5.5},
        {"name": "Генератор",             "brands": ["Bosch", "Valeo", "Denso"],             "sku": "GEN", "weight": 6.0},
        {"name": "Лампа головного света", "brands": ["Philips", "Osram", "Narva"],           "sku": "HBL", "weight": 0.05},
        {"name": "Датчик кислорода",      "brands": ["Bosch", "NGK", "Denso"],               "sku": "O2S", "weight": 0.2},
    ]},
    {"name": "Кузов", "parent": "", "children": [
        {"name": "Зеркало боковое",       "brands": ["Alkar", "Polcar", "Van Wezel"],        "sku": "MIR", "weight": 0.8},
        {"name": "Фара передняя",         "brands": ["Hella", "Depo", "Valeo"],              "sku": "HLA", "weight": 2.5},
        {"name": "Фонарь задний",         "brands": ["Hella", "Depo", "Valeo"],              "sku": "RLA", "weight": 1.5},
        {"name": "Бампер",                "brands": ["Polcar", "Van Wezel", "Klokkerholm"],  "sku": "BUM", "weight": 4.0, "pkg": "LARGE"},
        {"name": "Решётка радиатора",     "brands": ["Polcar", "Van Wezel"],                 "sku": "GRL", "weight": 1.2},
    ]},
    {"name": "Расходники", "parent": "", "children": [
        {"name": "Моторное масло 5W-30",  "brands": ["Castrol", "Mobil", "Liqui Moly", "Shell"], "sku": "OIM", "weight": 4.0},
        {"name": "Антифриз",              "brands": ["Castrol", "Liqui Moly", "Felix"],      "sku": "ANT", "weight": 5.0},
        {"name": "Дворники",              "brands": ["Bosch", "Valeo", "Trico"],             "sku": "WIP", "weight": 0.3},
    ]},
)


def _flatten_categories() -> list[dict]:
    """Возвращает плоский список «листовых» категорий с метаинформацией."""
    out = []
    for parent in PART_CATEGORIES:
        for child in parent.get("children", []):
            out.append({**child, "parent": parent["name"]})
    return out


def _stable_oem(brand: str, sku_prefix: str, model_id: str) -> str:
    """Детерминированный OEM-номер: префикс бренда + категория + хеш модели."""
    digest = hashlib.sha1(f"{brand}|{sku_prefix}|{model_id}".encode()).hexdigest()[:8].upper()
    return f"{brand[:3].upper()}-{sku_prefix}-{digest}"


def _stable_internal_sku(oem: str) -> str:
    return f"SYN-{oem}"


class SyntheticPartsDriver(PartsImportDriver):
    """
    Источник: ничего внешнего, только локальная генерация.

    Параметры:
      per_model_limit — сколько запчастей создавать на одну модель ТС
                        (по умолчанию 6 — равномерная выборка из всех категорий).
      seed_offset     — сдвиг при детерминированной выборке (для разнообразия).
    """

    name = "synthetic-parts"

    def __init__(self, *, per_model_default: int = 6, seed_offset: int = 0):
        self.per_model_default = max(1, per_model_default)
        self.seed_offset = seed_offset
        self._categories = _flatten_categories()

    # ── Категории ──────────────────────────────────────────
    def iter_categories(self) -> Iterable[PartCategoryEntry]:
        seen_parents: set[str] = set()
        # Сначала родительские
        for parent in PART_CATEGORIES:
            if parent["name"] not in seen_parents:
                yield PartCategoryEntry(name=parent["name"])
                seen_parents.add(parent["name"])
        # Потом дочерние
        for cat in self._categories:
            yield PartCategoryEntry(name=cat["name"], parent_name=cat["parent"])

    # ── Запчасти ───────────────────────────────────────────
    def iter_parts(
        self,
        *,
        makes: list[str] | None = None,
        models: list[str] | None = None,
        per_model_limit: int = 0,
    ) -> Iterable[PartEntry]:
        """
        Генерирует запчасти, опираясь на VehicleModel из БД.
        Если models не задан — берёт все из catalog.
        """
        from catalog.models import VehicleMake, VehicleModel

        per_model = per_model_limit or self.per_model_default

        qs = VehicleModel.objects.select_related("make").order_by("make__name", "name")
        if makes:
            qs = qs.filter(make__name__in=makes)
        if models:
            qs = qs.filter(name__in=models)

        category_count = len(self._categories)
        if category_count == 0:
            return

        # Уникальность OEM глобальная — сохраняем выданные коды,
        # чтобы при коллизиях (одна категория для разных моделей) сгенерировать вариант.
        seen_oems: set[str] = set()

        for idx, vm in enumerate(qs.iterator()):
            for j in range(per_model):
                cat_index = (idx + j + self.seed_offset) % category_count
                cat = self._categories[cat_index]
                brands = cat["brands"]
                brand = brands[(idx + j + self.seed_offset) % len(brands)]
                model_key = f"{vm.make.name}-{vm.name}-{vm.id}"
                oem = _stable_oem(brand, cat["sku"], model_key)
                # коллизию решаем добавлением суффикса (бывает редко)
                attempt = 0
                while oem in seen_oems and attempt < 5:
                    attempt += 1
                    oem = _stable_oem(brand, cat["sku"], f"{model_key}-{attempt}")
                seen_oems.add(oem)

                yield PartEntry(
                    internal_sku=_stable_internal_sku(oem),
                    name=f"{cat['name']} {brand} ({vm.make.name} {vm.name})",
                    oem_number=oem,
                    brand_name=brand,
                    category_name=cat["name"],
                    weight_kg=cat.get("weight"),
                    packaging_type=cat.get("pkg", "SMALL"),
                    applicable_to=((vm.make.name, vm.name),),
                )
