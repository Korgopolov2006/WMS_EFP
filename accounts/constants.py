from __future__ import annotations

from typing import Final


class Roles:
    ADMIN: Final[str] = "ADMIN"
    STOREKEEPER: Final[str] = "STOREKEEPER"
    SMALL_PARTS_PICKER: Final[str] = "SMALL_PARTS_PICKER"
    LOADER: Final[str] = "LOADER"
    SALES_MANAGER: Final[str] = "SALES_MANAGER"
    ANALYST: Final[str] = "ANALYST"
    INTEGRATION: Final[str] = "INTEGRATION"


ROLE_CHOICES = (
    (Roles.ADMIN, "Администратор"),
    (Roles.STOREKEEPER, "Кладовщик"),
    (Roles.SMALL_PARTS_PICKER, "Сборщик мелких деталей"),
    (Roles.LOADER, "Комплектовщик/грузчик"),
    (Roles.SALES_MANAGER, "Менеджер по продажам"),
    (Roles.ANALYST, "Аналитик"),
    (Roles.INTEGRATION, "Интеграционные сервисы (API)"),
)

