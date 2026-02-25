from __future__ import annotations

from decimal import Decimal

from .models import Product, ProductChangeLog


TRACKED_PRODUCT_FIELDS: tuple[tuple[str, str], ...] = (
    ("internal_sku", "Внутренний артикул"),
    ("name", "Наименование"),
    ("oem_number", "OEM номер"),
    ("analog_number", "Номер аналога"),
    ("brand", "Бренд"),
    ("category", "Категория"),
    ("weight_kg", "Вес, кг"),
    ("length_cm", "Длина, см"),
    ("width_cm", "Ширина, см"),
    ("height_cm", "Высота, см"),
    ("packaging_type", "Тип упаковки"),
    ("photo", "Фото"),
)


def _display_value(product: Product, field_name: str) -> str:
    if field_name == "brand":
        return product.brand.name if product.brand_id else "—"
    if field_name == "category":
        return product.category.name if product.category_id else "—"
    if field_name == "packaging_type":
        return product.get_packaging_type_display() if product.packaging_type else "—"
    if field_name == "photo":
        return product.photo.name if product.photo else "—"

    value = getattr(product, field_name, None)
    if value in (None, ""):
        return "—"
    if isinstance(value, Decimal):
        return str(value.normalize())
    return str(value)


def _display_applicability(product: Product) -> str:
    values = list(product.applicability.select_related("make").values_list("make__name", "name"))
    if not values:
        return "—"
    items = [f"{make} {model}" for make, model in values]
    return ", ".join(items[:8]) + (" ..." if len(items) > 8 else "")


def build_product_changes(
    *,
    before: Product | None,
    after: Product,
    action: str,
    changed_data: list[str] | None = None,
) -> dict[str, dict[str, str]]:
    changed_set = set(changed_data or [])
    changes: dict[str, dict[str, str]] = {}

    for field_name, label in TRACKED_PRODUCT_FIELDS:
        if action == ProductChangeLog.Action.UPDATE and changed_set and field_name not in changed_set:
            continue

        old_value = _display_value(before, field_name) if before else "—"
        new_value = _display_value(after, field_name)
        if action == ProductChangeLog.Action.CREATE:
            if new_value != "—":
                changes[field_name] = {"label": label, "old": "—", "new": new_value}
            continue
        if old_value != new_value:
            changes[field_name] = {"label": label, "old": old_value, "new": new_value}

    if action == ProductChangeLog.Action.CREATE or "applicability" in changed_set:
        old_ap = _display_applicability(before) if before else "—"
        new_ap = _display_applicability(after)
        if action == ProductChangeLog.Action.CREATE:
            if new_ap != "—":
                changes["applicability"] = {
                    "label": "Применимость",
                    "old": "—",
                    "new": new_ap,
                }
        elif old_ap != new_ap:
            changes["applicability"] = {
                "label": "Применимость",
                "old": old_ap,
                "new": new_ap,
            }

    return changes


def log_product_change(
    *,
    product: Product,
    user,
    action: str,
    changes: dict[str, dict[str, str]],
    source: str = "ui",
    note: str = "",
) -> ProductChangeLog | None:
    if action == ProductChangeLog.Action.UPDATE and not changes:
        return None
    return ProductChangeLog.objects.create(
        product=product,
        changed_by=user if getattr(user, "is_authenticated", False) else None,
        action=action,
        source=source,
        changed_fields=changes,
        note=note,
    )
