"""
Генерация штрихкодов и QR-кодов для товаров.

Используется в /catalog/codes/* эндпоинтах и в шаблонах этикеток.
Файлы не сохраняются на диск — отдаются в HttpResponse напрямую.
"""
from __future__ import annotations

import io
from typing import Literal

import barcode
import qrcode
from barcode.writer import ImageWriter

from .models import Product


def get_product_code(product: Product) -> str:
    """Возвращает значение для кодирования: barcode → fallback на internal_sku."""
    return (product.barcode or product.internal_sku or "").strip()


def find_product_by_code(code: str) -> Product | None:
    """
    Поиск товара по сканированному коду.
    Сначала по полю barcode, затем по internal_sku, затем по oem_number.
    """
    code = (code or "").strip()
    if not code:
        return None
    return (
        Product.objects.filter(barcode=code).first()
        or Product.objects.filter(internal_sku=code).first()
        or Product.objects.filter(oem_number__iexact=code).first()
    )


def render_barcode_png(
    value: str,
    fmt: Literal["code128", "ean13"] = "code128",
    module_height: float = 12.0,
    font_size: int = 10,
) -> bytes:
    """
    Генерирует PNG штрихкода. По умолчанию Code128 — поддерживает любые
    буквенно-цифровые значения (включая internal_sku). EAN13 строгий: ровно 12 цифр.
    """
    value = (value or "").strip()
    if not value:
        raise ValueError("Пустое значение для штрихкода.")

    if fmt == "ean13":
        digits = "".join(ch for ch in value if ch.isdigit())[:12].zfill(12)
        bc_cls = barcode.get_barcode_class("ean13")
        instance = bc_cls(digits, writer=ImageWriter())
    else:
        bc_cls = barcode.get_barcode_class("code128")
        instance = bc_cls(value, writer=ImageWriter())

    options = {
        "module_height": module_height,
        "font_size": font_size,
        "quiet_zone": 2.0,
        "write_text": True,
    }
    buf = io.BytesIO()
    instance.write(buf, options=options)
    return buf.getvalue()


def render_qr_png(value: str, box_size: int = 6, border: int = 2) -> bytes:
    """Генерирует PNG QR-кода для произвольного значения."""
    value = (value or "").strip()
    if not value:
        raise ValueError("Пустое значение для QR-кода.")

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(value)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()
