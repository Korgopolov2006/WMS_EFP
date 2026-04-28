"""
Импорт справочника марок и моделей ТС из внешнего источника.

Примеры:
    python manage.py import_vehicles --source carquery --year-from 2018 --year-to 2024
    python manage.py import_vehicles --makes ford,bmw --year-from 2020 --dry-run
    python manage.py import_vehicles --limit 50           # ограничить число записей (smoke-тест)
"""
from __future__ import annotations

from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalog.import_drivers import VehicleEntry, get_driver_for_command
from catalog.models import VehicleMake, VehicleModel


class Command(BaseCommand):
    help = "Импорт марок/моделей ТС из внешнего источника (по умолчанию: CarQuery)."

    def add_arguments(self, parser):
        parser.add_argument("--source", default="vpic",
                            choices=["vpic", "carquery"],
                            help="Источник данных. По умолчанию vpic (NHTSA, public domain). "
                                 "carquery — резервный вариант.")
        parser.add_argument("--year-from", type=int, default=2015)
        parser.add_argument("--year-to", type=int, default=datetime.now().year)
        parser.add_argument("--makes", default="",
                            help="Список make_id через запятую (ford,bmw). Пусто = все.")
        parser.add_argument("--limit", type=int, default=0,
                            help="Ограничить число обрабатываемых записей (0 = без лимита).")
        parser.add_argument("--dry-run", action="store_true",
                            help="Не писать в БД, только показать.")
        parser.add_argument("--insecure", action="store_true",
                            help="Отключить проверку SSL-сертификата (если у API временные проблемы).")
        parser.add_argument("--use-http", action="store_true",
                            help="Использовать http:// вместо https:// (для проблемных сертификатов).")

    def handle(self, *args, **opts):
        if opts["year_from"] > opts["year_to"]:
            raise CommandError("--year-from не может быть больше --year-to")

        makes = [m.strip() for m in (opts["makes"] or "").split(",") if m.strip()]
        driver = get_driver_for_command(opts)
        self.stdout.write(self.style.NOTICE(
            f"Источник: {driver.name} | годы {opts['year_from']}–{opts['year_to']}"
            + (f" | марки: {', '.join(makes)}" if makes else "")
            + (" | DRY-RUN" if opts["dry_run"] else "")
        ))

        created_makes = updated_makes = 0
        created_models = skipped_models = 0
        processed = 0

        try:
            entries = driver.iter_entries(
                year_from=opts["year_from"],
                year_to=opts["year_to"],
                makes=makes or None,
            )
            for entry in entries:
                if opts["limit"] and processed >= opts["limit"]:
                    break
                processed += 1
                cm, cmod, sm = self._upsert(entry, dry_run=opts["dry_run"])
                created_makes += cm
                updated_makes += cmod
                if sm == "created":
                    created_models += 1
                else:
                    skipped_models += 1

                if processed % 50 == 0:
                    self.stdout.write(f"  обработано {processed}: {entry.make_name} / {entry.model_name}")

        except Exception as exc:
            raise CommandError(f"Импорт прерван: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(
            f"Готово. Записей: {processed}. "
            f"Марок создано: {created_makes}. "
            f"Моделей создано: {created_models}, пропущено (дубликаты): {skipped_models}."
        ))

    @transaction.atomic
    def _upsert(self, entry: VehicleEntry, *, dry_run: bool) -> tuple[int, int, str]:
        """Возвращает (created_make: 0|1, updated_make: 0|1, model_status: 'created'|'skipped')."""
        make_name = (entry.make_name or "").strip()
        model_name = (entry.model_name or "").strip()
        if not make_name or not model_name:
            return 0, 0, "skipped"

        if dry_run:
            self.stdout.write(f"  DRY: {make_name} / {model_name}")
            return 0, 0, "skipped"

        make, made = VehicleMake.objects.get_or_create(name=make_name)
        _, model_made = VehicleModel.objects.get_or_create(make=make, name=model_name)
        return (1 if made else 0), 0, ("created" if model_made else "skipped")
