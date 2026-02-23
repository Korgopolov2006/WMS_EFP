from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db.models import Q

from .models import Product
from .normalization import normalize_part_number


def find_duplicate_product_by_numbers(
    *,
    oem_number: str | None,
    analog_number: str | None,
    exclude_id: int | None = None,
) -> Product | None:
    oem_norm = normalize_part_number(oem_number)
    analog_norm = normalize_part_number(analog_number)

    if not oem_norm and not analog_norm:
        return None

    q = Q()
    if oem_norm:
        q |= Q(oem_number_normalized=oem_norm) | Q(analog_number_normalized=oem_norm)
    if analog_norm:
        q |= Q(oem_number_normalized=analog_norm) | Q(analog_number_normalized=analog_norm)

    qs = Product.objects.select_related("brand").filter(q)
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    return qs.order_by("id").first()


def validate_product_numbers_uniqueness(
    *,
    oem_number: str | None,
    analog_number: str | None,
    exclude_id: int | None = None,
) -> None:
    oem_norm = normalize_part_number(oem_number)
    analog_norm = normalize_part_number(analog_number)

    if not oem_norm:
        raise ValidationError("OEM номер обязателен.")
    if analog_norm and analog_norm == oem_norm:
        raise ValidationError("Номер аналога не должен совпадать с OEM после нормализации.")

    duplicate = find_duplicate_product_by_numbers(
        oem_number=oem_number,
        analog_number=analog_number,
        exclude_id=exclude_id,
    )
    if duplicate:
        raise ValidationError(
            (
                f"Обнаружен дубликат по OEM/аналогу: "
                f"{duplicate.internal_sku} — {duplicate.name} (OEM {duplicate.oem_number})"
            )
        )
