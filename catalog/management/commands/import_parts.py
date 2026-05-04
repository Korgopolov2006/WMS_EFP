"""
Импорт каталога запчастей.

Примеры:
    # Сгенерировать запчасти для всех машин в БД (по 6 на модель):
    python manage.py import_parts

    # Только для определённых марок:
    python manage.py import_parts --makes Ford,BMW

    # 12 запчастей на каждую модель:
    python manage.py import_parts --per-model 12

    # Тестовый прогон без записи:
    python manage.py import_parts --limit 30 --dry-run
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalog.import_drivers import PartEntry, get_parts_driver
from catalog.models import (
    Brand,
    Category,
    Product,
    ProductApplicability,
    VehicleMake,
    VehicleModel,
)


class Command(BaseCommand):
    help = "Импорт каталога запчастей. По умолчанию: synthetic-parts."

    def add_arguments(self, parser):
        parser.add_argument("--source", default="synthetic-parts",
                            choices=["synthetic-parts", "synthetic", "synth"],
                            help="Источник данных")
        parser.add_argument("--makes", default="",
                            help="Список марок через запятую (Ford,BMW). Пусто = все.")
        parser.add_argument("--models", default="",
                            help="Список моделей через запятую. Пусто = все.")
        parser.add_argument("--per-model", type=int, default=6,
                            help="Сколько запчастей создавать на одну модель ТС.")
        parser.add_argument("--seed-offset", type=int, default=0,
                            help="Сдвиг при детерминированной выборке (для разнообразия).")
        parser.add_argument("--limit", type=int, default=0,
                            help="Ограничить число обрабатываемых записей.")
        parser.add_argument("--skip-categories", action="store_true",
                            help="Не создавать новые категории (полагаться на существующие).")
        parser.add_argument("--dry-run", action="store_true",
                            help="Не писать в БД, только показать.")

    def handle(self, *args, **opts):
        if not VehicleMake.objects.exists():
            raise CommandError(
                "В БД нет ни одной марки ТС. Сначала запустите `import_vehicles`."
            )

        makes = [m.strip() for m in (opts["makes"] or "").split(",") if m.strip()]
        models = [m.strip() for m in (opts["models"] or "").split(",") if m.strip()]

        driver = get_parts_driver({
            "source": opts["source"],
            "per_model": opts["per_model"],
            "seed_offset": opts["seed_offset"],
        })

        self.stdout.write(self.style.NOTICE(
            f"Источник: {driver.name} | per_model={opts['per_model']}"
            + (f" | марки: {', '.join(makes)}" if makes else "")
            + (f" | модели: {', '.join(models)}" if models else "")
            + (" | DRY-RUN" if opts["dry_run"] else "")
        ))

        # 1) Категории
        cats_created = 0
        if not opts["skip_categories"] and not opts["dry_run"]:
            cats_created = self._import_categories(driver)
            if cats_created:
                self.stdout.write(f"  + категорий: {cats_created}")

        # 2) Запчасти
        created_products = updated_products = applied = 0
        processed = 0
        try:
            for entry in driver.iter_parts(
                makes=makes or None,
                models=models or None,
                per_model_limit=opts["per_model"],
            ):
                if opts["limit"] and processed >= opts["limit"]:
                    break
                processed += 1
                cp, up, ap = self._upsert_part(entry, dry_run=opts["dry_run"])
                created_products += cp
                updated_products += up
                applied += ap

                if processed % 50 == 0:
                    self.stdout.write(
                        f"  обработано {processed}: {entry.brand_name} {entry.name[:60]}"
                    )

        except Exception as exc:
            raise CommandError(f"Импорт запчастей прерван: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(
            f"Готово. Записей: {processed}. "
            f"Категорий: {cats_created}. "
            f"Товаров создано: {created_products}, обновлено: {updated_products}. "
            f"Применимость: {applied} связей."
        ))

    # ── Категории ──────────────────────────────────────────

    @transaction.atomic
    def _import_categories(self, driver) -> int:
        created = 0
        for entry in driver.iter_categories():
            _, made = Category.objects.get_or_create(name=entry.name)
            if made:
                created += 1
        return created

    # ── Один товар ─────────────────────────────────────────

    def _upsert_part(self, entry: PartEntry, *, dry_run: bool) -> tuple[int, int, int]:
        """Возвращает (created, updated, applicability_links)."""
        if dry_run:
            self.stdout.write(
                f"  DRY: {entry.brand_name} | {entry.category_name} | "
                f"{entry.oem_number} | {entry.name[:60]}"
            )
            return 0, 0, 0

        with transaction.atomic():
            brand, _ = Brand.objects.get_or_create(name=entry.brand_name)
            category, _ = Category.objects.get_or_create(name=entry.category_name)

            product, created = Product.objects.get_or_create(
                internal_sku=entry.internal_sku,
                defaults={
                    "name": entry.name,
                    "oem_number": entry.oem_number,
                    "analog_number": entry.analog_number or "",
                    "brand": brand,
                    "category": category,
                    "packaging_type": entry.packaging_type,
                    "weight_kg": entry.weight_kg,
                },
            )
            updated = 0
            if not created:
                changed = False
                if product.name != entry.name:
                    product.name = entry.name
                    changed = True
                if entry.weight_kg is not None and product.weight_kg != entry.weight_kg:
                    product.weight_kg = entry.weight_kg
                    changed = True
                if changed:
                    try:
                        product.save()
                        updated = 1
                    except Exception:
                        # validate_product_numbers_uniqueness может ругнуться —
                        # пропускаем без падения всей команды
                        pass

            applied = self._apply_to_models(product, entry.applicable_to)

        return (1 if created else 0), updated, applied

    # ── Применимость ───────────────────────────────────────

    def _apply_to_models(self, product, applicable_to) -> int:
        """Создаёт ProductApplicability для каждой пары (make, model), если ещё нет."""
        if not applicable_to:
            return 0
        applied = 0
        for make_name, model_name in applicable_to:
            vm = (
                VehicleModel.objects
                .filter(make__name=make_name, name=model_name)
                .first()
            )
            if not vm:
                continue
            _, made = ProductApplicability.objects.get_or_create(
                product=product, vehicle_model=vm
            )
            if made:
                applied += 1
        return applied
