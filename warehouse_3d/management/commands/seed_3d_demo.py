"""
Команда: создаёт демо-объекты 3D-склада с привязкой к местам хранения.

    python manage.py seed_3d_demo                  # для всех складов
    python manage.py seed_3d_demo --warehouse=MAIN # только для одного
    python manage.py seed_3d_demo --reset          # удалить старые 3D-объекты и пересоздать

После выполнения 3D-стеллажи появятся в окне «📦 Выбрать на 3D-стеллаже»
в форме строки приёмки.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import StorageLocation, Warehouse
from warehouse_3d.models import StorageObject, WarehouseLayout


# Шаблон ряда: (object_type, default_size, prefix, count_per_zone_type)
DEFAULT_RECIPE = [
    {
        "object_type": StorageObject.ObjectType.RACK,
        "code_prefix": "R",
        "width": 2.0, "depth": 1.0, "height": 2.5,
        "preferred_zone": "SHELF",
    },
    {
        "object_type": StorageObject.ObjectType.SHELF,
        "code_prefix": "SH",
        "width": 1.5, "depth": 0.8, "height": 0.3,
        "preferred_zone": "SHELF",
    },
    {
        "object_type": StorageObject.ObjectType.CELL,
        "code_prefix": "CL",
        "width": 0.5, "depth": 0.5, "height": 0.5,
        "preferred_zone": "CELL",
    },
    {
        "object_type": StorageObject.ObjectType.FLOOR,
        "code_prefix": "FL",
        "width": 2.0, "depth": 2.0, "height": 0.1,
        "preferred_zone": "FLOOR",
    },
]


class Command(BaseCommand):
    help = "Создаёт 3D-объекты с привязкой к StorageLocation для интеграции с приёмкой."

    def add_arguments(self, parser):
        parser.add_argument("--warehouse", help="Код склада (например MAIN). По умолчанию — все.")
        parser.add_argument("--reset", action="store_true", help="Удалить существующие 3D-объекты склада.")
        parser.add_argument("--max-per-type", type=int, default=4,
                            help="Сколько объектов каждого типа создать максимум (по умолчанию 4).")

    @transaction.atomic
    def handle(self, *args, **opts):
        wh_code = opts.get("warehouse")
        reset = opts.get("reset")
        max_per_type = opts.get("max_per_type")

        warehouses = Warehouse.objects.filter(is_active=True)
        if wh_code:
            warehouses = warehouses.filter(code=wh_code)
        if not warehouses.exists():
            self.stderr.write(self.style.ERROR("Не найдено активных складов."))
            return

        total_created = 0
        for wh in warehouses:
            self.stdout.write(self.style.NOTICE(f"\n=== Склад {wh.branch.code}/{wh.code} — {wh.name} ==="))

            # 1) Гарантируем layout с минимальным контуром
            layout, _ = WarehouseLayout.objects.get_or_create(warehouse=wh)
            if not layout.is_layout_defined or len(layout.floor_points) < 3:
                layout.floor_points = [[-10, -10], [10, -10], [10, 10], [-10, 10]]
                layout.is_layout_defined = True
                layout.save()
                self.stdout.write("  - kontur sklada sozdan (kvadrat 20x20 m)")

            # 2) Очистка по запросу
            if reset:
                deleted = StorageObject.objects.filter(warehouse=wh).delete()[0]
                self.stdout.write(self.style.WARNING(f"  · удалено существующих объектов: {deleted}"))

            # 3) Берём доступные локации этого склада, группируем по типу зоны
            locations = list(
                StorageLocation.objects
                .filter(zone__warehouse=wh)
                .select_related("zone__zone_type")
                .order_by("zone__zone_type__sort_order", "zone__code", "code")
            )
            if not locations:
                self.stdout.write(self.style.WARNING(
                    "  · НЕТ мест хранения у этого склада. "
                    "Создайте их в /admin/catalog/storagelocation/ или /control/wms/"
                ))
                continue

            locations_by_zone_type = {}
            for loc in locations:
                zt = loc.zone.zone_type.code if loc.zone and loc.zone.zone_type else ""
                locations_by_zone_type.setdefault(zt, []).append(loc)

            # 4) Создаём по шаблону, не дублируя то что уже есть
            existing_codes = set(
                StorageObject.objects.filter(warehouse=wh).values_list("code", flat=True)
            )

            x_cursor = -8.0
            z_cursor = -8.0
            created_for_wh = 0

            for recipe in DEFAULT_RECIPE:
                pool = (
                    locations_by_zone_type.get(recipe["preferred_zone"])
                    or locations  # fallback — любые локации
                )
                if not pool:
                    continue
                count = min(max_per_type, len(pool))
                for i in range(count):
                    code = f"{recipe['code_prefix']}-{i + 1:02d}"
                    if code in existing_codes:
                        continue
                    pos_x = x_cursor + i * (recipe["width"] + 0.5)
                    pos_z = z_cursor
                    StorageObject.objects.create(
                        warehouse=wh,
                        object_type=recipe["object_type"],
                        code=code,
                        name=f"{recipe['object_type']} {code}",
                        position_x=round(pos_x, 2),
                        position_y=0.0,
                        position_z=round(pos_z, 2),
                        width=recipe["width"],
                        depth=recipe["depth"],
                        height=recipe["height"],
                        rotation_y=0.0,
                        storage_location=pool[i],
                    )
                    existing_codes.add(code)
                    created_for_wh += 1
                z_cursor += recipe["depth"] + 1.5

            # Если объекты уже были и --reset не указан, попробуем привязать их
            # к локациям, если у них пусто
            unbound = StorageObject.objects.filter(
                warehouse=wh, is_active=True, storage_location__isnull=True,
            ).order_by("id")
            if unbound.exists():
                self.stdout.write(f"  · нашлось {unbound.count()} объектов без привязки — привязываю…")
                pool_iter = iter(locations)
                bound = 0
                for obj in unbound:
                    try:
                        loc = next(pool_iter)
                    except StopIteration:
                        break
                    obj.storage_location = loc
                    obj.save(update_fields=["storage_location"])
                    bound += 1
                self.stdout.write(self.style.SUCCESS(f"    привязано: {bound}"))

            total_created += created_for_wh
            self.stdout.write(self.style.SUCCESS(
                f"  · создано новых объектов: {created_for_wh}"
            ))

        self.stdout.write(self.style.SUCCESS(
            f"\n[OK] Gotovo. Vsego sozdano 3D-objektov: {total_created}"
        ))
        self.stdout.write(
            "Otkroyte /control/3d/ — uvidite stellazhi. "
            "V forme priomki oni poyavyatsya v 'Vybrat na 3D-stellazhe'."
        )
