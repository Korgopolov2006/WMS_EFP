from django.core.management.base import BaseCommand

from reports.services import generate_report_snapshots


class Command(BaseCommand):
    help = "Автоматически пересчитывает и сохраняет снимки ключевых отчётов."

    def add_arguments(self, parser):
        parser.add_argument("--period", type=int, default=30, help="Период анализа в днях")
        parser.add_argument("--dead-stock-days", type=int, default=90, help="Порог мёртвых остатков в днях")
        parser.add_argument("--forecast-days", type=int, default=7, help="Горизонт прогноза спроса в днях")

    def handle(self, *args, **options):
        summary = generate_report_snapshots(
            period_days=max(7, min(365, options["period"])),
            dead_stock_days=max(1, min(3650, options["dead_stock_days"])),
            forecast_days=max(1, min(90, options["forecast_days"])),
        )
        self.stdout.write(self.style.SUCCESS("Автогенерация отчётов завершена"))
        self.stdout.write(
            "ABC-XYZ: {abc_xyz}; мёртвые остатки: {dead_stock}; "
            "аналоги: {analogs}; прогноз спроса: {demand_forecast}; "
            "ошибки подбора за период: {picking_errors}; сотрудников в анализе: {staff_efficiency}".format(**summary)
        )
