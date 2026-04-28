"""
Базовый интерфейс драйверов импорта внешних справочников.

Два направления:
  • VehicleImportDriver — машины (марка + модель)
  • PartsImportDriver   — запчасти (PartEntry)
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class VehicleEntry:
    """Один импортируемый автомобиль (марка + модель)."""
    make_name: str
    model_name: str


@dataclass(frozen=True)
class PartEntry:
    """
    Один импортируемый товар (запчасть).
    Связи с автомобилями опциональные — будут привязаны через ProductApplicability,
    если соответствующие VehicleModel существуют в БД.
    """
    internal_sku: str
    name: str
    oem_number: str
    brand_name: str
    category_name: str
    analog_number: str = ""
    packaging_type: str = "SMALL"          # SMALL | LARGE | PALLET
    weight_kg: float | None = None
    # Списки имён машин, к которым применима запчасть.
    # Каждая запись — пара (make_name, model_name); проставляется по факту в ProductApplicability.
    applicable_to: tuple[tuple[str, str], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PartCategoryEntry:
    """Категория запчасти (для импорта в catalog.Category)."""
    name: str
    parent_name: str = ""


class VehicleImportDriver:
    """Контракт драйвера: возвращает iterable VehicleEntry для диапазона лет."""

    name: str = "base"

    def list_makes(self) -> list[str]:
        raise NotImplementedError

    def iter_entries(
        self,
        *,
        year_from: int,
        year_to: int,
        makes: list[str] | None = None,
    ) -> Iterable[VehicleEntry]:
        raise NotImplementedError


class PartsImportDriver:
    """
    Контракт драйвера для импорта запчастей.
    """

    name: str = "base-parts"

    def iter_categories(self) -> Iterable[PartCategoryEntry]:
        return iter(())

    def iter_parts(
        self,
        *,
        makes: list[str] | None = None,
        models: list[str] | None = None,
        per_model_limit: int = 0,
    ) -> Iterable[PartEntry]:
        raise NotImplementedError
