from __future__ import annotations

import argparse
from datetime import datetime, UTC
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
    ) -> str:
        cell_id = self._id()
        style = (
            "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;"
            "html=1;endArrow=block;endFill=1;strokeColor=#5f6368;strokeWidth=1.4;"
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


def build_structure_diagram(output: Path) -> None:
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
            "modified": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    )
    diagram = ET.SubElement(mxfile, "diagram", {"name": "Структурная схема", "id": "wms-structure"})
    model = ET.SubElement(
        diagram,
        "mxGraphModel",
        {
            "dx": "1800",
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
            "pageWidth": "2200",
            "pageHeight": "1400",
            "math": "0",
            "shadow": "0",
        },
    )
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    b = DrawioBuilder()

    container_style = (
        "rounded=1;whiteSpace=wrap;html=1;strokeColor=#c6c6c6;fillColor=#f8f9fa;"
        "fontStyle=1;align=left;verticalAlign=top;spacing=10;arcSize=12;"
    )
    role_style = (
        "rounded=1;whiteSpace=wrap;html=1;strokeColor=#7e57c2;fillColor=#ede7f6;"
        "fontColor=#4a148c;fontStyle=1;align=center;verticalAlign=middle;arcSize=12;"
    )
    app_style = (
        "rounded=1;whiteSpace=wrap;html=1;strokeColor=#1e88e5;fillColor=#e3f2fd;"
        "fontColor=#0d47a1;fontStyle=1;align=center;verticalAlign=middle;arcSize=12;"
    )
    backend_style = (
        "rounded=1;whiteSpace=wrap;html=1;strokeColor=#2e7d32;fillColor=#e8f5e9;"
        "fontColor=#1b5e20;fontStyle=1;align=center;verticalAlign=middle;arcSize=12;"
    )
    infra_style = (
        "rounded=1;whiteSpace=wrap;html=1;strokeColor=#ef6c00;fillColor=#fff3e0;"
        "fontColor=#e65100;fontStyle=1;align=center;verticalAlign=middle;arcSize=12;"
    )
    ext_style = (
        "rounded=1;whiteSpace=wrap;html=1;strokeColor=#c62828;fillColor=#ffebee;"
        "fontColor=#b71c1c;fontStyle=1;align=center;verticalAlign=middle;arcSize=12;"
    )

    # Containers
    b.add_vertex(
        root,
        value="<b>Пользовательский слой</b>",
        style=container_style,
        x=30,
        y=20,
        w=420,
        h=760,
    )
    b.add_vertex(
        root,
        value="<b>Приложение WMS (Django)</b>",
        style=container_style,
        x=470,
        y=20,
        w=760,
        h=980,
    )
    b.add_vertex(
        root,
        value="<b>Инфраструктура и внешние сервисы</b>",
        style=container_style,
        x=1250,
        y=20,
        w=900,
        h=980,
    )

    # Role / client panels
    admin = b.add_vertex(root, value="Администратор", style=role_style, x=60, y=70, w=170, h=54)
    storekeeper = b.add_vertex(root, value="Кладовщик", style=role_style, x=250, y=70, w=170, h=54)
    picker = b.add_vertex(root, value="Сборщик", style=role_style, x=60, y=140, w=170, h=54)
    loader = b.add_vertex(root, value="Грузчик", style=role_style, x=250, y=140, w=170, h=54)
    sales = b.add_vertex(root, value="Менеджер продаж", style=role_style, x=60, y=210, w=170, h=54)
    analyst = b.add_vertex(root, value="Аналитик", style=role_style, x=250, y=210, w=170, h=54)
    api_client = b.add_vertex(root, value="Внешний API клиент", style=role_style, x=60, y=300, w=360, h=54)
    ops = b.add_vertex(root, value="Ops: Celery Control Center", style=role_style, x=60, y=370, w=360, h=54)

    # App blocks
    frontend = b.add_vertex(
        root,
        value="Web Frontend<br/><font style='font-size:11px'>Django templates + JS + 3D UI</font>",
        style=app_style,
        x=520,
        y=70,
        w=660,
        h=80,
    )
    api_v1 = b.add_vertex(
        root,
        value="REST API v1<br/><font style='font-size:11px'>Token auth, Swagger/ReDoc</font>",
        style=app_style,
        x=520,
        y=170,
        w=660,
        h=80,
    )
    views = b.add_vertex(
        root,
        value="URL Router + Views<br/><font style='font-size:11px'>core, accounts, catalog, receiving, inventory, picking, tasks, reports, warehouse_3d</font>",
        style=backend_style,
        x=520,
        y=270,
        w=660,
        h=96,
    )
    business = b.add_vertex(
        root,
        value="Бизнес-логика / сервисы<br/><font style='font-size:11px'>TaskService, ReceivingService, Inventory/Picking flows, отчёты</font>",
        style=backend_style,
        x=520,
        y=386,
        w=660,
        h=96,
    )
    efp_queue = b.add_vertex(
        root,
        value="EFP Queue Manager<br/><font style='font-size:11px'>efp.queue (enqueue, status, fallback)</font>",
        style=backend_style,
        x=520,
        y=502,
        w=660,
        h=84,
    )
    orm = b.add_vertex(
        root,
        value="Data Access Layer<br/><font style='font-size:11px'>Django ORM / models</font>",
        style=backend_style,
        x=520,
        y=606,
        w=660,
        h=80,
    )
    db = b.add_vertex(
        root,
        value="PostgreSQL<br/><font style='font-size:11px'>wms_autoparts</font>",
        style=infra_style,
        x=520,
        y=706,
        w=660,
        h=90,
    )

    # Infra / external
    redis = b.add_vertex(
        root,
        value="Redis<br/><font style='font-size:11px'>Cache + Celery Broker/Result</font>",
        style=infra_style,
        x=1300,
        y=120,
        w=380,
        h=84,
    )
    celery = b.add_vertex(
        root,
        value="Celery Worker<br/><font style='font-size:11px'>wms.celery + efp.tasks</font>",
        style=infra_style,
        x=1300,
        y=224,
        w=380,
        h=84,
    )
    watchdog = b.add_vertex(
        root,
        value="Watchdog / Scheduler<br/><font style='font-size:11px'>scripts/watchdog_celery.ps1 + Task Scheduler</font>",
        style=infra_style,
        x=1300,
        y=328,
        w=380,
        h=90,
    )
    efp_service = b.add_vertex(
        root,
        value="EFP Integration Service<br/><font style='font-size:11px'>efp.services (HTTP parsing, caching)</font>",
        style=ext_style,
        x=1300,
        y=438,
        w=380,
        h=90,
    )
    efp_external = b.add_vertex(
        root,
        value="EFP Parts (efp-parts.ru)",
        style=ext_style,
        x=1300,
        y=548,
        w=380,
        h=68,
    )
    api_tokens = b.add_vertex(
        root,
        value="API Tokens / Integration Auth<br/><font style='font-size:11px'>api_apitoken</font>",
        style=infra_style,
        x=1700,
        y=120,
        w=420,
        h=84,
    )
    files = b.add_vertex(
        root,
        value="Static/Media Files<br/><font style='font-size:11px'>photos, CSS/JS</font>",
        style=infra_style,
        x=1700,
        y=224,
        w=420,
        h=84,
    )

    # Main flow
    for role_id in [admin, storekeeper, picker, loader, sales, analyst]:
        b.add_edge(root, source=role_id, target=frontend, dashed=True)
    b.add_edge(root, source=api_client, target=api_v1, dashed=True)

    b.add_edge(root, source=frontend, target=views)
    b.add_edge(root, source=api_v1, target=views)
    b.add_edge(root, source=views, target=business)
    b.add_edge(root, source=business, target=efp_queue)
    b.add_edge(root, source=business, target=orm)
    b.add_edge(root, source=orm, target=db)

    # Infra links
    b.add_edge(root, source=business, target=redis, dashed=True, value="cache")
    b.add_edge(root, source=efp_queue, target=celery, dashed=True, value="async tasks")
    b.add_edge(root, source=celery, target=redis, dashed=True, value="broker/result")
    b.add_edge(root, source=celery, target=efp_service)
    b.add_edge(root, source=efp_service, target=efp_external)
    b.add_edge(root, source=watchdog, target=celery, dashed=True)
    b.add_edge(root, source=ops, target=watchdog, dashed=True)
    b.add_edge(root, source=ops, target=redis, dashed=True)
    b.add_edge(root, source=ops, target=celery, dashed=True)
    b.add_edge(root, source=api_v1, target=api_tokens, dashed=True)
    b.add_edge(root, source=frontend, target=files, dashed=True)

    xml_data = ET.tostring(mxfile, encoding="utf-8", xml_declaration=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(xml_data)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate WMS application structure diagram (.drawio)")
    parser.add_argument("--output", default="db/структурная схема.drawio", help="Path to output drawio file")
    args = parser.parse_args()
    build_structure_diagram(Path(args.output))
    print(f"Generated: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
