from __future__ import annotations

import re
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q, Count
from django.utils import timezone

from accounts.models import User
from catalog.models import Brand, Category, Product, VehicleModel
from picking.models import Order
from receiving.models import Receiving, Supplier
from reports.models import PickingError
from tasks.models import Task, TaskComment


KEYWORDS = ("demo", "test", "демо", "тест")


def _contains_keywords_q(*fields: str) -> Q:
    q = Q()
    for field in fields:
        for kw in KEYWORDS:
            q |= Q(**{f"{field}__icontains": kw})
    return q


def _slug_token(value: str, max_len: int = 8) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", (value or "").upper())
    return cleaned[:max_len]


def _save_existing_fields(instance, fields: list[str]) -> None:
    existing = {f.name for f in instance._meta.fields}
    update_fields = [field for field in fields if field in existing]
    if update_fields:
        instance.save(update_fields=update_fields)
    else:
        instance.save()


class Command(BaseCommand):
    help = "Удаляет/нормализует demo/test-данные и заполняет реальные позиции по всем моделям ТС."

    def add_arguments(self, parser):
        parser.add_argument("--products-per-model", type=int, default=5)

    @transaction.atomic
    def handle(self, *args, **options):
        products_per_model: int = max(1, min(5, int(options["products_per_model"])))

        self.stdout.write(self.style.NOTICE("1) Очистка demo/test данных..."))
        cleanup_stats = self._cleanup_demo_test_data()

        self.stdout.write(self.style.NOTICE("2) Подготовка справочников поставщиков/брендов/категорий..."))
        suppliers = self._ensure_real_suppliers()
        brands, categories = self._ensure_real_reference_data()
        self._normalize_receiving_supplier_data(suppliers)

        self.stdout.write(self.style.NOTICE("3) Заполнение товаров с применимостью по каждой модели..."))
        seed_stats = self._seed_products_for_all_models(brands, categories, products_per_model=products_per_model)

        models_total = VehicleModel.objects.count()
        models_with_products = VehicleModel.objects.filter(products__isnull=False).distinct().count()
        uncovered = models_total - models_with_products
        min_links = (
            VehicleModel.objects.annotate(pc=Count("products"))
            .order_by("pc")
            .values_list("pc", flat=True)
            .first()
            or 0
        )

        self.stdout.write(self.style.SUCCESS("Готово. Итоги:"))
        for k, v in cleanup_stats.items():
            self.stdout.write(f"  cleanup.{k}: {v}")
        for k, v in seed_stats.items():
            self.stdout.write(f"  seed.{k}: {v}")
        self.stdout.write(f"  coverage.models_total: {models_total}")
        self.stdout.write(f"  coverage.models_with_products: {models_with_products}")
        self.stdout.write(f"  coverage.models_without_products: {uncovered}")
        self.stdout.write(f"  coverage.min_products_per_model: {min_links}")

    def _cleanup_demo_test_data(self) -> dict[str, int]:
        stats: dict[str, int] = {}

        # Комментарии и задачи демонстрации.
        q_task_comments = _contains_keywords_q("text")
        deleted_comments, _ = TaskComment.objects.filter(q_task_comments).delete()
        stats["task_comments_deleted"] = deleted_comments

        q_tasks = _contains_keywords_q("title", "description")
        deleted_tasks, _ = Task.objects.filter(q_tasks).delete()
        stats["tasks_deleted"] = deleted_tasks

        # Ошибки подбора из демо-отчётов.
        q_pick_errors = _contains_keywords_q("error_type", "notes")
        deleted_pick_errors, _ = PickingError.objects.filter(q_pick_errors).delete()
        stats["picking_errors_deleted"] = deleted_pick_errors

        # Заказы с demo/test (если есть).
        q_orders = _contains_keywords_q(
            "number",
            "customer_name",
            "customer_phone",
            "customer_email",
            "external_id",
            "window_number",
        )
        deleted_orders, _ = Order.objects.filter(q_orders).delete()
        stats["orders_deleted"] = deleted_orders

        # Поставщики/приёмки с demo/test будут нормализованы ниже, но проблемные отдельные сущности удаляем.
        q_suppliers = _contains_keywords_q("code", "name")
        deleted_suppliers, _ = Supplier.objects.filter(q_suppliers).delete()
        stats["suppliers_deleted"] = deleted_suppliers

        # Справочники с demo/test: переименовываем, чтобы не ломать связи с товарами.
        q_brands = _contains_keywords_q("name")
        brands_renamed = 0
        for brand in Brand.objects.filter(q_brands).order_by("id"):
            brand.name = f"Real Brand {brand.id}"
            brand.save(update_fields=["name", "updated_at"])
            brands_renamed += 1
        stats["brands_renamed"] = brands_renamed

        q_categories = _contains_keywords_q("name")
        categories_renamed = 0
        for category in Category.objects.filter(q_categories).order_by("id"):
            category.name = f"Реальная категория {category.id}"
            category.save(update_fields=["name", "updated_at"])
            categories_renamed += 1
        stats["categories_renamed"] = categories_renamed

        # Пользователей не удаляем (из-за связанных документов), а переименовываем.
        q_users = _contains_keywords_q("username", "first_name", "last_name", "email")
        renamed = 0
        for user in User.objects.filter(q_users).order_by("id"):
            if user.is_superuser:
                continue
            old_username = user.username
            base_username = f"worker_{user.id}"
            candidate = base_username
            i = 1
            while User.objects.exclude(pk=user.pk).filter(username=candidate).exists():
                i += 1
                candidate = f"{base_username}_{i}"
            user.username = candidate
            if user.email and any(kw in user.email.lower() for kw in KEYWORDS):
                user.email = ""
            if user.first_name and any(kw in user.first_name.lower() for kw in KEYWORDS):
                user.first_name = ""
            if user.last_name and any(kw in user.last_name.lower() for kw in KEYWORDS):
                user.last_name = ""
            if user.username != old_username:
                renamed += 1
            _save_existing_fields(user, ["username", "email", "first_name", "last_name", "updated_at"])
        stats["users_renamed"] = renamed

        return stats

    def _ensure_real_suppliers(self) -> list[Supplier]:
        items = [
            ("ROSSKO", "РОССКО"),
            ("EXIST", "Exist.ru"),
            ("EMEX", "Emex"),
            ("AUTODOC", "Autodoc"),
            ("BERG", "Berg Автокомплект"),
            ("FORUMAUTO", "Форум-Авто"),
        ]
        suppliers: list[Supplier] = []
        for code, name in items:
            supplier, _ = Supplier.objects.get_or_create(code=code, defaults={"name": name})
            if supplier.name != name:
                supplier.name = name
                _save_existing_fields(supplier, ["name", "updated_at"])
            suppliers.append(supplier)
        return suppliers

    def _normalize_receiving_supplier_data(self, suppliers: list[Supplier]) -> None:
        # Подчищаем старые приёмки с demo/test по имени поставщика/номеру документа.
        preferred = suppliers[0] if suppliers else None
        if not preferred:
            return

        q_rec = _contains_keywords_q("supplier_name", "supplier_doc_no")
        for rec in Receiving.objects.filter(q_rec).order_by("id"):
            rec.supplier_name = preferred.name
            if any(kw in (rec.supplier_doc_no or "").lower() for kw in KEYWORDS) or not rec.supplier_doc_no:
                rec.supplier_doc_no = f"SDOC-{preferred.code}-{timezone.localdate():%Y%m%d}-{rec.id:04d}"
            _save_existing_fields(rec, ["supplier_name", "supplier_doc_no", "updated_at"])

    def _ensure_real_reference_data(self) -> tuple[dict[str, Brand], dict[str, Category]]:
        brand_names = [
            "MANN-FILTER",
            "Mahle",
            "Bosch",
            "TRW",
            "Brembo",
            "NGK",
            "Denso",
            "Valeo",
            "SKF",
            "Aisin",
        ]
        category_names = [
            "Масляные фильтры",
            "Воздушные фильтры",
            "Салонные фильтры",
            "Тормозные колодки",
            "Тормозные диски",
        ]

        brands: dict[str, Brand] = {}
        for name in brand_names:
            obj, _ = Brand.objects.get_or_create(name=name)
            brands[name] = obj

        categories: dict[str, Category] = {}
        for name in category_names:
            obj, _ = Category.objects.get_or_create(name=name)
            categories[name] = obj

        return brands, categories

    def _seed_products_for_all_models(
        self,
        brands: dict[str, Brand],
        categories: dict[str, Category],
        *,
        products_per_model: int,
    ) -> dict[str, int]:
        templates = [
            {
                "code": "OF",
                "name": "Фильтр масляный",
                "brand": "MANN-FILTER",
                "category": "Масляные фильтры",
                "packaging_type": Product.PackagingType.SMALL,
                "weight_kg": Decimal("0.35"),
                "size": (8, 8, 9),
            },
            {
                "code": "AF",
                "name": "Фильтр воздушный",
                "brand": "Mahle",
                "category": "Воздушные фильтры",
                "packaging_type": Product.PackagingType.SMALL,
                "weight_kg": Decimal("0.42"),
                "size": (28, 20, 5),
            },
            {
                "code": "CF",
                "name": "Фильтр салонный",
                "brand": "Bosch",
                "category": "Салонные фильтры",
                "packaging_type": Product.PackagingType.SMALL,
                "weight_kg": Decimal("0.25"),
                "size": (24, 20, 4),
            },
            {
                "code": "BP",
                "name": "Колодки тормозные передние",
                "brand": "TRW",
                "category": "Тормозные колодки",
                "packaging_type": Product.PackagingType.SMALL,
                "weight_kg": Decimal("1.15"),
                "size": (17, 12, 7),
            },
            {
                "code": "BD",
                "name": "Диск тормозной передний",
                "brand": "Brembo",
                "category": "Тормозные диски",
                "packaging_type": Product.PackagingType.LARGE,
                "weight_kg": Decimal("6.40"),
                "size": (31, 31, 6),
            },
        ][:products_per_model]

        created = 0
        updated = 0
        applicability_added = 0

        for vm in VehicleModel.objects.select_related("make").order_by("make__name", "name"):
            make_name = vm.make.name
            model_name = vm.name
            make_token = _slug_token(make_name, max_len=6) or f"MK{vm.make_id}"
            model_token = _slug_token(model_name, max_len=8) or f"MD{vm.id}"

            for idx, tpl in enumerate(templates, start=1):
                part_code = tpl["code"]
                sku = f"{make_token}-{model_token}-{part_code}-{vm.id:03d}"[:64]
                oem = f"{make_token}{vm.id:03d}{part_code}{idx}"[:64]
                brand = brands[tpl["brand"]]
                category = categories[tpl["category"]]
                analog = f"{_slug_token(brand.name, 6) or 'BR'}{vm.id:03d}{part_code}"[:64]
                length_cm, width_cm, height_cm = tpl["size"]

                product, was_created = Product.objects.get_or_create(
                    internal_sku=sku,
                    defaults={
                        "name": f"{tpl['name']} {make_name} {model_name}",
                        "oem_number": oem,
                        "analog_number": analog,
                        "brand": brand,
                        "category": category,
                        "packaging_type": tpl["packaging_type"],
                        "weight_kg": tpl["weight_kg"],
                        "length_cm": Decimal(str(length_cm)),
                        "width_cm": Decimal(str(width_cm)),
                        "height_cm": Decimal(str(height_cm)),
                    },
                )
                if was_created:
                    created += 1
                else:
                    changed = False
                    if not product.name:
                        product.name = f"{tpl['name']} {make_name} {model_name}"
                        changed = True
                    if not product.oem_number:
                        product.oem_number = oem
                        changed = True
                    if not product.brand_id:
                        product.brand = brand
                        changed = True
                    if not product.category_id:
                        product.category = category
                        changed = True
                    if changed:
                        product.save()
                        updated += 1

                if not product.applicability.filter(pk=vm.pk).exists():
                    product.applicability.add(vm)
                    applicability_added += 1

        return {
            "products_created": created,
            "products_updated": updated,
            "applicability_links_added": applicability_added,
            "products_total": Product.objects.count(),
        }
