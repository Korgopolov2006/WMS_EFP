from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET


class DrawioBuilder:
    def __init__(self) -> None:
        self.next_id = 2

    def _id(self) -> str:
        value = str(self.next_id)
        self.next_id += 1
        return value

    def add_vertex(
        self,
        root: ET.Element,
        *,
        value: str,
        style: str,
        x: int,
        y: int,
        w: int,
        h: int,
    ) -> str:
        cell_id = self._id()
        cell = ET.SubElement(
            root,
            "mxCell",
            {
                "id": cell_id,
                "value": value,
                "style": style,
                "vertex": "1",
                "parent": "1",
            },
        )
        ET.SubElement(
            cell,
            "mxGeometry",
            {"x": str(x), "y": str(y), "width": str(w), "height": str(h), "as": "geometry"},
        )
        return cell_id

    def add_edge(
        self,
        root: ET.Element,
        *,
        source: str,
        target: str,
        value: str = "",
        dashed: bool = False,
        color: str = "#5f6368",
    ) -> str:
        cell_id = self._id()
        style = (
            "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;"
            f"html=1;endArrow=block;endFill=1;strokeColor={color};strokeWidth=1.5;"
            "fontSize=11;labelBackgroundColor=#ffffff;"
        )
        if dashed:
            style += "dashed=1;dashPattern=6 6;"
        edge = ET.SubElement(
            root,
            "mxCell",
            {
                "id": cell_id,
                "value": value,
                "style": style,
                "edge": "1",
                "parent": "1",
                "source": source,
                "target": target,
            },
        )
        ET.SubElement(edge, "mxGeometry", {"relative": "1", "as": "geometry"})
        return cell_id


def build_functional_diagram(output: Path) -> None:
    mxfile = ET.Element(
        "mxfile",
        {
            "host": "Electron",
            "agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) draw.io/28.2.8 Chrome/140.0.7339.240 "
                "Electron/38.4.0 Safari/537.36"
            ),
            "version": "28.2.8",
            "modified": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    )
    diagram = ET.SubElement(mxfile, "diagram", {"name": "Функциональная схема", "id": "wms-functional"})
    model = ET.SubElement(
        diagram,
        "mxGraphModel",
        {
            "dx": "1700",
            "dy": "1200",
            "grid": "1",
            "gridSize": "10",
            "guides": "1",
            "tooltips": "1",
            "connect": "1",
            "arrows": "1",
            "fold": "1",
            "page": "1",
            "pageScale": "1",
            "pageWidth": "2300",
            "pageHeight": "1500",
            "math": "0",
            "shadow": "0",
        },
    )
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    b = DrawioBuilder()

    lane_style = (
        "rounded=1;whiteSpace=wrap;html=1;strokeColor=#d0d0d0;fillColor=#f8f9fa;"
        "fontStyle=1;align=left;verticalAlign=top;spacing=10;arcSize=10;"
    )
    role_style = (
        "rounded=1;whiteSpace=wrap;html=1;strokeColor=#7e57c2;fillColor=#ede7f6;"
        "fontColor=#4a148c;fontStyle=1;align=center;verticalAlign=middle;arcSize=12;"
    )
    system_style = (
        "rounded=1;whiteSpace=wrap;html=1;strokeColor=#1565c0;fillColor=#e3f2fd;"
        "fontColor=#0d47a1;fontStyle=1;align=center;verticalAlign=middle;arcSize=12;"
    )
    process_style = (
        "rounded=1;whiteSpace=wrap;html=1;strokeColor=#2e7d32;fillColor=#e8f5e9;"
        "fontColor=#1b5e20;align=center;verticalAlign=middle;arcSize=12;"
    )
    async_style = (
        "rounded=1;whiteSpace=wrap;html=1;strokeColor=#ef6c00;fillColor=#fff3e0;"
        "fontColor=#e65100;align=center;verticalAlign=middle;arcSize=12;"
    )
    data_style = (
        "shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;size=15;"
        "strokeColor=#455a64;fillColor=#eceff1;fontColor=#263238;fontStyle=1;"
    )
    decision_style = (
        "rhombus;whiteSpace=wrap;html=1;strokeColor=#c62828;fillColor=#ffebee;"
        "fontColor=#b71c1c;fontStyle=1;"
    )

    # Swimlanes / sections
    b.add_vertex(root, value="<b>Роли и точки входа</b>", style=lane_style, x=20, y=20, w=420, h=740)
    b.add_vertex(root, value="<b>Операционный контур WMS</b>", style=lane_style, x=460, y=20, w=980, h=1240)
    b.add_vertex(root, value="<b>Интеграции и фон</b>", style=lane_style, x=1460, y=20, w=800, h=1240)

    # Roles
    role_storekeeper = b.add_vertex(root, value="Кладовщик", style=role_style, x=50, y=70, w=160, h=52)
    role_sales = b.add_vertex(root, value="Менеджер продаж", style=role_style, x=230, y=70, w=180, h=52)
    role_picker = b.add_vertex(root, value="Сборщик", style=role_style, x=50, y=140, w=160, h=52)
    role_loader = b.add_vertex(root, value="Грузчик", style=role_style, x=230, y=140, w=180, h=52)
    role_analyst = b.add_vertex(root, value="Аналитик", style=role_style, x=50, y=210, w=160, h=52)
    role_admin = b.add_vertex(root, value="Администратор", style=role_style, x=230, y=210, w=180, h=52)
    role_api = b.add_vertex(root, value="Внешние системы (API)", style=role_style, x=50, y=290, w=360, h=52)
    role_ops = b.add_vertex(root, value="Ops/Сервис", style=role_style, x=50, y=360, w=360, h=52)

    # Core system entry
    frontend = b.add_vertex(
        root,
        value="Web UI / 3D склад / Ролевой дашборд",
        style=system_style,
        x=520,
        y=70,
        w=860,
        h=72,
    )
    api_v1 = b.add_vertex(
        root,
        value="REST API v1 (token auth, OpenAPI, Swagger/ReDoc)",
        style=system_style,
        x=520,
        y=160,
        w=860,
        h=72,
    )

    # Receiving functional chain
    recv_create = b.add_vertex(root, value="Создание приёмки", style=process_style, x=520, y=270, w=260, h=64)
    recv_add = b.add_vertex(
        root,
        value="Добавление строк товара\n(локальная проверка + EFP при необходимости)",
        style=process_style,
        x=820,
        y=270,
        w=320,
        h=74,
    )
    recv_decision = b.add_vertex(root, value="Товар найден\nлокально?", style=decision_style, x=1180, y=270, w=170, h=90)
    recv_place = b.add_vertex(
        root,
        value="Автоназначение\nмест хранения\nпо складу/филиалу",
        style=process_style,
        x=820,
        y=370,
        w=320,
        h=80,
    )
    recv_complete = b.add_vertex(root, value="Завершение приёмки\n+ обновление остатков", style=process_style, x=520, y=380, w=260, h=70)

    # Order -> picking -> shipping chain
    order_create = b.add_vertex(root, value="Создание/подтверждение заказа", style=process_style, x=520, y=500, w=260, h=64)
    task_generate = b.add_vertex(root, value="Генерация задач подбора", style=process_style, x=820, y=500, w=320, h=64)
    picking_exec = b.add_vertex(root, value="Выполнение подбора\n(CELL/SHELF/FLOOR)", style=process_style, x=1180, y=500, w=200, h=74)
    picked_status = b.add_vertex(root, value="Статус заказа: PICKED", style=process_style, x=820, y=590, w=320, h=64)
    shipping = b.add_vertex(root, value="Отгрузка и выдача", style=process_style, x=520, y=590, w=260, h=64)

    # Inventory / control chain
    inv_start = b.add_vertex(root, value="Запуск инвентаризации", style=process_style, x=520, y=700, w=260, h=64)
    inv_recount = b.add_vertex(root, value="Пересчёт / расхождения", style=process_style, x=820, y=700, w=320, h=64)
    inv_apply = b.add_vertex(root, value="Применение корректировок", style=process_style, x=1180, y=700, w=200, h=64)

    # Tasks / monitoring
    tasks = b.add_vertex(
        root,
        value="Контур задач\n(tasks, comments, monitoring)",
        style=system_style,
        x=520,
        y=800,
        w=860,
        h=74,
    )
    reports = b.add_vertex(
        root,
        value="Отчёты: ABC/XYZ, dead stock,\nошибки подбора, прогноз спроса, эффективность",
        style=system_style,
        x=520,
        y=894,
        w=860,
        h=84,
    )

    # Data
    orm = b.add_vertex(root, value="Django ORM / Service Layer", style=system_style, x=520, y=1000, w=860, h=72)
    db = b.add_vertex(root, value="PostgreSQL (wms_autoparts)", style=data_style, x=760, y=1090, w=380, h=90)

    # Integrations / async
    efp_queue = b.add_vertex(
        root,
        value="EFP Queue Manager\n(enqueue/status/fallback)",
        style=async_style,
        x=1510,
        y=120,
        w=330,
        h=84,
    )
    celery = b.add_vertex(root, value="Celery Worker", style=async_style, x=1860, y=120, w=330, h=84)
    redis = b.add_vertex(root, value="Redis\n(cache + broker/result)", style=async_style, x=1510, y=224, w=330, h=84)
    watchdog = b.add_vertex(root, value="Watchdog / Task Scheduler", style=async_style, x=1860, y=224, w=330, h=84)
    efp = b.add_vertex(root, value="EFP service (HTTP parsing)", style=async_style, x=1510, y=328, w=330, h=84)
    efp_site = b.add_vertex(root, value="EFP Parts (efp-parts.ru)", style=async_style, x=1860, y=328, w=330, h=84)
    docs = b.add_vertex(root, value="API Docs (Swagger/ReDoc/OpenAPI)", style=async_style, x=1510, y=430, w=330, h=74)

    # Relations (roles -> entries)
    for rid in [role_storekeeper, role_sales, role_picker, role_loader, role_analyst, role_admin]:
        b.add_edge(root, source=rid, target=frontend, dashed=True)
    b.add_edge(root, source=role_api, target=api_v1, dashed=True)
    b.add_edge(root, source=role_ops, target=watchdog, dashed=True)
    b.add_edge(root, source=role_ops, target=celery, dashed=True)

    # Main functional edges
    b.add_edge(root, source=frontend, target=recv_create)
    b.add_edge(root, source=frontend, target=order_create)
    b.add_edge(root, source=frontend, target=inv_start)
    b.add_edge(root, source=frontend, target=tasks)
    b.add_edge(root, source=api_v1, target=recv_create, dashed=True)
    b.add_edge(root, source=api_v1, target=order_create, dashed=True)
    b.add_edge(root, source=api_v1, target=tasks, dashed=True)
    b.add_edge(root, source=api_v1, target=docs, dashed=True)

    # Receiving branch
    b.add_edge(root, source=recv_create, target=recv_add)
    b.add_edge(root, source=recv_add, target=recv_decision)
    b.add_edge(root, source=recv_decision, target=recv_place, value="Да")
    b.add_edge(root, source=recv_place, target=recv_complete)
    b.add_edge(root, source=recv_decision, target=efp_queue, value="Нет", dashed=True, color="#ef6c00")
    b.add_edge(root, source=efp_queue, target=recv_place, value="результат", dashed=True, color="#ef6c00")

    # Order/picking/shipping branch
    b.add_edge(root, source=order_create, target=task_generate)
    b.add_edge(root, source=task_generate, target=picking_exec)
    b.add_edge(root, source=picking_exec, target=picked_status)
    b.add_edge(root, source=picked_status, target=shipping)

    # Inventory branch
    b.add_edge(root, source=inv_start, target=inv_recount)
    b.add_edge(root, source=inv_recount, target=inv_apply)

    # Task/reporting + data
    b.add_edge(root, source=recv_complete, target=tasks)
    b.add_edge(root, source=shipping, target=tasks)
    b.add_edge(root, source=inv_apply, target=tasks)
    b.add_edge(root, source=tasks, target=reports)
    b.add_edge(root, source=tasks, target=orm)
    b.add_edge(root, source=reports, target=orm)
    b.add_edge(root, source=orm, target=db)

    # Async infra links
    b.add_edge(root, source=efp_queue, target=celery, dashed=True, value="dispatch")
    b.add_edge(root, source=celery, target=redis, dashed=True, value="broker/result")
    b.add_edge(root, source=celery, target=efp)
    b.add_edge(root, source=efp, target=efp_site)
    b.add_edge(root, source=watchdog, target=celery, dashed=True, value="health/restart")
    b.add_edge(root, source=orm, target=redis, dashed=True, value="cache")

    xml_data = ET.tostring(mxfile, encoding="utf-8", xml_declaration=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(xml_data)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate WMS functional diagram (.drawio)")
    parser.add_argument("--output", default="db/функциональная схема.drawio", help="Path to output drawio file")
    args = parser.parse_args()
    build_functional_diagram(Path(args.output))
    print(f"Generated: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
