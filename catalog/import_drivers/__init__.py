"""
Драйверы импорта внешних справочников ТС.
Используется management-командой `import_vehicles`.
"""
from .base import VehicleEntry, VehicleImportDriver
from .carquery import CarQueryDriver
from .vpic import VpicDriver


def get_driver(name: str, **kwargs) -> VehicleImportDriver:
    name = (name or "").strip().lower()
    if name == "carquery":
        return CarQueryDriver(**kwargs)
    if name == "vpic":
        return VpicDriver(**kwargs)
    raise ValueError(f"Неизвестный источник: {name}. Доступно: carquery, vpic.")


def get_driver_for_command(opts: dict) -> VehicleImportDriver:
    """
    Создаёт драйвер с учётом аргументов management-команды.
    Изолировано чтобы тесты могли мокать только эту фабрику.
    """
    name = (opts.get("source") or "vpic").lower()
    if name == "carquery":
        return CarQueryDriver(
            verify_ssl=not opts.get("insecure", False),
            use_http=opts.get("use_http", False),
        )
    if name == "vpic":
        return VpicDriver(verify_ssl=not opts.get("insecure", False))
    return get_driver(name)


__all__ = [
    "CarQueryDriver",
    "VehicleEntry",
    "VehicleImportDriver",
    "VpicDriver",
    "get_driver",
    "get_driver_for_command",
]
