"""
Драйверы импорта внешних справочников ТС и запчастей.

Машины:    `import_vehicles` (источники: vpic, carquery)
Запчасти:  `import_parts`    (источники: synthetic-parts, wikidata-categories)
"""
from .base import (
    PartCategoryEntry,
    PartEntry,
    PartsImportDriver,
    VehicleEntry,
    VehicleImportDriver,
)
from .carquery import CarQueryDriver
from .parts_synth import SyntheticPartsDriver
from .vpic import VpicDriver


def get_driver(name: str, **kwargs):
    """Универсальная фабрика. Возвращает Vehicle- или Parts-драйвер по имени."""
    name = (name or "").strip().lower()
    if name == "carquery":
        return CarQueryDriver(**kwargs)
    if name == "vpic":
        return VpicDriver(**kwargs)
    if name in ("synthetic", "synthetic-parts", "synth"):
        return SyntheticPartsDriver(**kwargs)
    raise ValueError(
        f"Неизвестный источник: {name}. "
        f"Доступно: carquery, vpic, synthetic-parts."
    )


def get_driver_for_command(opts: dict) -> VehicleImportDriver:
    """Драйвер для команды `import_vehicles` (учитывает SSL-флаги)."""
    name = (opts.get("source") or "vpic").lower()
    if name == "carquery":
        return CarQueryDriver(
            verify_ssl=not opts.get("insecure", False),
            use_http=opts.get("use_http", False),
        )
    if name == "vpic":
        return VpicDriver(verify_ssl=not opts.get("insecure", False))
    return get_driver(name)


def get_parts_driver(opts: dict) -> PartsImportDriver:
    """Драйвер для команды `import_parts`."""
    name = (opts.get("source") or "synthetic-parts").lower()
    if name in ("synthetic", "synthetic-parts", "synth"):
        return SyntheticPartsDriver(
            per_model_default=opts.get("per_model", 6),
            seed_offset=opts.get("seed_offset", 0),
        )
    raise ValueError(f"Неизвестный источник запчастей: {name}.")


__all__ = [
    "CarQueryDriver",
    "PartCategoryEntry",
    "PartEntry",
    "PartsImportDriver",
    "SyntheticPartsDriver",
    "VehicleEntry",
    "VehicleImportDriver",
    "VpicDriver",
    "get_driver",
    "get_driver_for_command",
    "get_parts_driver",
]
