from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET


class Builder:
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
        w: int = 240,
        h: int = 56,
    ) -> str:
        cid = self._id()
        cell = ET.SubElement(
            root,
            "mxCell",
            {
                "id": cid,
                "value": value,
                "style": style,
                "vertex": "1",
                "parent": "1",
            },
        )
        ET.SubElement(
            cell,
            "mxGeometry",
            {
                "x": str(x),
                "y": str(y),
                "width": str(w),
                "height": str(h),
                "as": "geometry",
            },
        )
        return cid

    def add_edge(
        self,
        root: ET.Element,
        *,
        source: str,
        target: str,
        style: str,
        value: str = "",
        points: list[tuple[int, int]] | None = None,
    ) -> str:
        cid = self._id()
        edge = ET.SubElement(
            root,
            "mxCell",
            {
                "id": cid,
                "value": value,
                "style": style,
                "edge": "1",
                "parent": "1",
                "source": source,
                "target": target,
            },
        )
        geom = ET.SubElement(edge, "mxGeometry", {"relative": "1", "as": "geometry"})
        if points:
            arr = ET.SubElement(geom, "Array", {"as": "points"})
            for x, y in points:
                ET.SubElement(arr, "mxPoint", {"x": str(x), "y": str(y)})
        return cid


def build_ui_navigation(output: Path) -> None:
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
    diagram = ET.SubElement(
        mxfile,
        "diagram",
        {"name": "Схема пользовательского интерфейса WMS", "id": "wms-ui-navigation"},
    )
    model = ET.SubElement(
        diagram,
        "mxGraphModel",
        {
            "dx": "2400",
            "dy": "1500",
            "grid": "1",
            "gridSize": "10",
            "guides": "1",
            "tooltips": "1",
            "connect": "1",
            "arrows": "1",
            "fold": "1",
            "page": "1",
            "pageScale": "1",
            "pageWidth": "3900",
            "pageHeight": "2300",
            "math": "0",
            "shadow": "0",
        },
    )
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    b = Builder()

    lane_style = (
        "rounded=1;whiteSpace=wrap;html=1;strokeColor=#d2d6dc;fillColor=#f7f8fa;"
        "fontStyle=1;align=left;verticalAlign=top;spacing=8;"
    )
    header_style = (
        "rounded=1;whiteSpace=wrap;html=1;strokeColor=#aab2bd;fillColor=#eef1f5;"
        "fontStyle=1;align=center;verticalAlign=middle;fontSize=13;"
    )
    card_style = (
        "rounded=0;whiteSpace=wrap;html=1;strokeColor=#8f99a8;fillColor=#e9edf2;"
        "align=center;verticalAlign=middle;fontSize=12;"
    )
    card_main_style = (
        "rounded=0;whiteSpace=wrap;html=1;strokeColor=#6f7a89;fillColor=#dfe6ee;"
        "fontStyle=1;align=center;verticalAlign=middle;fontSize=12;"
    )
    edge_style = (
        "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;"
        "html=1;endArrow=block;endFill=1;strokeColor=#5f6368;strokeWidth=1.3;fontSize=11;"
    )
    dashed_edge_style = (
        "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;"
        "html=1;endArrow=block;endFill=1;strokeColor=#7b7f87;strokeWidth=1.2;fontSize=11;"
        "dashed=1;dashPattern=6 4;"
    )

    # Containers.
    b.add_vertex(root, value="<b>Точка входа</b>", style=lane_style, x=20, y=40, w=520, h=1500)
    b.add_vertex(root, value="<b>Разделы главной панели</b>", style=lane_style, x=560, y=40, w=520, h=1500)
    b.add_vertex(root, value="<b>Рабочие окна разделов</b>", style=lane_style, x=1100, y=40, w=760, h=1500)
    b.add_vertex(root, value="<b>Детальные окна и действия</b>", style=lane_style, x=1880, y=40, w=960, h=1500)
    b.add_vertex(root, value="<b>Вспомогательные API/служебные окна</b>", style=lane_style, x=2860, y=40, w=900, h=1500)

    b.add_vertex(root, value="UI Flow WMS", style=header_style, x=1520, y=6, w=660, h=28)

    # Level 1: entry.
    login = b.add_vertex(root, value="Окно входа\n/accounts/login/", style=card_main_style, x=90, y=520, w=360, h=64)
    dashboard = b.add_vertex(root, value="Главная панель\n/ (dashboard)", style=card_main_style, x=90, y=620, w=360, h=64)
    b.add_edge(root, source=login, target=dashboard, style=edge_style)

    # Level 2: dashboard sections.
    account = b.add_vertex(root, value="Личный кабинет\n/accounts/me/", style=card_style, x=640, y=190, w=360, h=58)
    manual = b.add_vertex(root, value="Руководство\n/manual/", style=card_style, x=640, y=270, w=360, h=58)
    integrations = b.add_vertex(root, value="Интеграции\n/integrations/", style=card_style, x=640, y=350, w=360, h=58)
    catalog = b.add_vertex(root, value="Каталог и админ-контур\n/catalog/admin/", style=card_style, x=640, y=470, w=360, h=58)
    receiving = b.add_vertex(root, value="Приемка\n/receiving/", style=card_style, x=640, y=560, w=360, h=58)
    inventory = b.add_vertex(root, value="Инвентаризация и остатки\n/inventory/", style=card_style, x=640, y=650, w=360, h=58)
    picking = b.add_vertex(root, value="Заказы и подбор\n/picking/", style=card_style, x=640, y=740, w=360, h=58)
    tasks = b.add_vertex(root, value="Задачи\n/tasks/", style=card_style, x=640, y=830, w=360, h=58)
    reports = b.add_vertex(root, value="Отчеты\n/reports/", style=card_style, x=640, y=920, w=360, h=58)
    warehouse3d = b.add_vertex(root, value="3D склад\n/3d/warehouse/<id>/", style=card_style, x=640, y=1010, w=360, h=58)

    # Dashboard fan-out via side trunk.
    trunk_x = 560
    for target, y in [
        (account, 219),
        (manual, 299),
        (integrations, 379),
        (catalog, 499),
        (receiving, 589),
        (inventory, 679),
        (picking, 769),
        (tasks, 859),
        (reports, 949),
        (warehouse3d, 1039),
    ]:
        b.add_edge(root, source=dashboard, target=target, style=edge_style, points=[(trunk_x, 652), (trunk_x, y), (640, y)])

    # Level 3/4: account/manual/integrations.
    logout = b.add_vertex(root, value="Выход\n/accounts/logout/", style=card_style, x=1180, y=190, w=300, h=58)
    manual_download = b.add_vertex(root, value="Скачать руководство\n/manual/download/", style=card_style, x=1180, y=270, w=300, h=58)
    efp_search = b.add_vertex(root, value="Поиск EFP\n/efp/search/", style=card_style, x=1180, y=350, w=300, h=58)
    efp_detail = b.add_vertex(root, value="Детали EFP\n/efp/detail/", style=card_style, x=1940, y=350, w=300, h=58)

    b.add_edge(root, source=account, target=logout, style=edge_style)
    b.add_edge(root, source=manual, target=manual_download, style=edge_style)
    b.add_edge(root, source=integrations, target=efp_search, style=edge_style)
    b.add_edge(root, source=efp_search, target=efp_detail, style=edge_style)
    b.add_edge(root, source=logout, target=login, style=dashed_edge_style, points=[(1330, 219), (1330, 120), (270, 120), (270, 552)])

    # Catalog.
    catalog_products = b.add_vertex(root, value="Список товаров\n/catalog/admin/products/", style=card_style, x=1180, y=450, w=300, h=58)
    catalog_products_audit = b.add_vertex(root, value="Аудит товаров\n/catalog/admin/products/audit/", style=card_style, x=1180, y=520, w=300, h=58)
    catalog_forms = b.add_vertex(
        root,
        value="Формы справочников\nbrands/categories/vehicles/zones\n(new/edit/list)",
        style=card_style,
        x=1180,
        y=590,
        w=300,
        h=86,
    )
    catalog_storage_map = b.add_vertex(root, value="Карта хранения\n/catalog/admin/storage/map/", style=card_style, x=1940, y=450, w=320, h=58)
    catalog_product_form = b.add_vertex(root, value="Создание/редактирование товара\n.../products/new, .../<id>/edit", style=card_style, x=1940, y=520, w=320, h=68)
    catalog_xref = b.add_vertex(root, value="Кросс-ссылки товара\n.../products/<id>/xref/", style=card_style, x=1940, y=600, w=320, h=58)
    catalog_api = b.add_vertex(
        root,
        value="Catalog API endpoints\n/catalog/api/warehouses/*",
        style=card_style,
        x=2920,
        y=450,
        w=300,
        h=58,
    )

    b.add_edge(root, source=catalog, target=catalog_products, style=edge_style)
    b.add_edge(root, source=catalog, target=catalog_products_audit, style=edge_style)
    b.add_edge(root, source=catalog, target=catalog_forms, style=edge_style)
    b.add_edge(root, source=catalog_products, target=catalog_product_form, style=edge_style)
    b.add_edge(root, source=catalog_products, target=catalog_xref, style=edge_style)
    b.add_edge(root, source=catalog, target=catalog_storage_map, style=edge_style, points=[(1000, 430), (1700, 430), (1940, 479)])
    b.add_edge(root, source=catalog_storage_map, target=catalog_api, style=dashed_edge_style)
    b.add_edge(root, source=catalog_storage_map, target=warehouse3d, style=dashed_edge_style, value="3D визуализация")

    # Receiving.
    recv_list = b.add_vertex(root, value="Список приемок\n/receiving/", style=card_style, x=1180, y=700, w=300, h=58)
    recv_suppliers = b.add_vertex(root, value="Поставщики\n/receiving/suppliers/", style=card_style, x=1180, y=770, w=300, h=58)
    recv_new = b.add_vertex(root, value="Новая приемка\n/receiving/new/", style=card_style, x=1180, y=840, w=300, h=58)
    recv_detail = b.add_vertex(root, value="Карточка приемки\n/receiving/<id>/", style=card_style, x=1940, y=840, w=320, h=58)
    recv_actions = b.add_vertex(
        root,
        value="Действия в приемке\nadd-line, suggest-location,\nnew-product, product-prefill, pdf",
        style=card_style,
        x=1940,
        y=910,
        w=320,
        h=86,
    )
    recv_supplier_new = b.add_vertex(root, value="Новый поставщик\n/receiving/suppliers/new/", style=card_style, x=1940, y=770, w=320, h=58)
    recv_next_doc = b.add_vertex(root, value="След. номер документа\n/receiving/next-supplier-doc/", style=card_style, x=2920, y=840, w=300, h=58)

    b.add_edge(root, source=receiving, target=recv_list, style=edge_style)
    b.add_edge(root, source=receiving, target=recv_suppliers, style=edge_style)
    b.add_edge(root, source=receiving, target=recv_new, style=edge_style)
    b.add_edge(root, source=recv_suppliers, target=recv_supplier_new, style=edge_style)
    b.add_edge(root, source=recv_list, target=recv_detail, style=edge_style, points=[(1480, 729), (1710, 729), (1940, 869)])
    b.add_edge(root, source=recv_new, target=recv_detail, style=edge_style)
    b.add_edge(root, source=recv_detail, target=recv_actions, style=edge_style)
    b.add_edge(root, source=recv_new, target=recv_next_doc, style=dashed_edge_style, points=[(1660, 869), (1660, 1210), (2720, 1210), (2920, 869)])
    b.add_edge(root, source=recv_actions, target=efp_search, style=dashed_edge_style, value="поиск аналога EFP")

    # Inventory.
    stock_list = b.add_vertex(root, value="Остатки: список\n/inventory/stock/", style=card_style, x=1180, y=1010, w=300, h=58)
    stock_detail = b.add_vertex(root, value="Остатки: карточка\n/inventory/stock/<id>/", style=card_style, x=1940, y=1010, w=320, h=58)
    inv_list = b.add_vertex(root, value="Инвентаризации: список\n/inventory/inventory/", style=card_style, x=1180, y=1080, w=300, h=58)
    inv_new = b.add_vertex(root, value="Новая инвентаризация\n/inventory/inventory/new/", style=card_style, x=1940, y=1080, w=320, h=58)
    inv_detail = b.add_vertex(root, value="Карточка инвентаризации\n/inventory/inventory/<id>/", style=card_style, x=1940, y=1150, w=320, h=58)

    b.add_edge(root, source=inventory, target=stock_list, style=edge_style)
    b.add_edge(root, source=stock_list, target=stock_detail, style=edge_style)
    b.add_edge(root, source=inventory, target=inv_list, style=edge_style)
    b.add_edge(root, source=inv_list, target=inv_new, style=edge_style)
    b.add_edge(root, source=inv_list, target=inv_detail, style=edge_style)
    b.add_edge(root, source=inv_new, target=inv_detail, style=edge_style)

    # Picking.
    order_list = b.add_vertex(root, value="Заказы: список\n/picking/orders/", style=card_style, x=1180, y=1240, w=300, h=58)
    order_new = b.add_vertex(root, value="Новый заказ\n/picking/orders/new/", style=card_style, x=1940, y=1220, w=320, h=58)
    order_detail = b.add_vertex(root, value="Карточка заказа\n/picking/orders/<id>/", style=card_style, x=1940, y=1290, w=320, h=58)
    order_line_delete = b.add_vertex(root, value="Удаление строки заказа\n.../lines/<line_id>/delete/", style=card_style, x=2920, y=1290, w=300, h=58)
    picking_tasks_list = b.add_vertex(root, value="Задачи подбора\n/picking/tasks/", style=card_style, x=1180, y=1310, w=300, h=58)
    picking_task_detail = b.add_vertex(root, value="Карточка задачи подбора\n/picking/tasks/<id>/", style=card_style, x=1940, y=1360, w=320, h=58)
    picking_ajax = b.add_vertex(root, value="Поиск товара (AJAX)\n/picking/ajax/product-search/", style=card_style, x=2920, y=1220, w=300, h=58)

    b.add_edge(root, source=picking, target=order_list, style=edge_style)
    b.add_edge(root, source=order_list, target=order_new, style=edge_style)
    b.add_edge(root, source=order_list, target=order_detail, style=edge_style)
    b.add_edge(root, source=order_new, target=order_detail, style=edge_style)
    b.add_edge(root, source=order_detail, target=order_line_delete, style=edge_style)
    b.add_edge(root, source=picking, target=picking_tasks_list, style=edge_style)
    b.add_edge(root, source=picking_tasks_list, target=picking_task_detail, style=edge_style)
    b.add_edge(root, source=order_new, target=picking_ajax, style=dashed_edge_style)

    # Tasks.
    tasks_list = b.add_vertex(root, value="Список задач\n/tasks/", style=card_style, x=1180, y=1410, w=300, h=58)
    tasks_detail = b.add_vertex(root, value="Карточка задачи\n/tasks/<id>/", style=card_style, x=1940, y=1430, w=320, h=58)
    tasks_monitoring = b.add_vertex(root, value="Мониторинг задач\n/tasks/monitoring/", style=card_style, x=1180, y=1480, w=300, h=58)
    tasks_monitoring_api = b.add_vertex(root, value="Monitoring API\n/tasks/api/monitoring/", style=card_style, x=2920, y=1480, w=300, h=58)

    b.add_edge(root, source=tasks, target=tasks_list, style=edge_style)
    b.add_edge(root, source=tasks_list, target=tasks_detail, style=edge_style)
    b.add_edge(root, source=tasks, target=tasks_monitoring, style=edge_style)
    b.add_edge(root, source=tasks_monitoring, target=tasks_monitoring_api, style=dashed_edge_style)

    # Reports.
    reports_home = b.add_vertex(root, value="Главная отчетов\n/reports/", style=card_style, x=1180, y=1570, w=300, h=58)
    reports_pages = b.add_vertex(
        root,
        value="Страницы отчетов\nabc-xyz, dead-stock,\nanalogs, picking-errors,\ndemand-forecast, staff-efficiency",
        style=card_style,
        x=1940,
        y=1540,
        w=320,
        h=100,
    )
    reports_api = b.add_vertex(root, value="Report Data API\n/reports/api/<type>/", style=card_style, x=2920, y=1570, w=300, h=58)

    b.add_edge(root, source=reports, target=reports_home, style=edge_style)
    b.add_edge(root, source=reports_home, target=reports_pages, style=edge_style)
    b.add_edge(root, source=reports_pages, target=reports_api, style=dashed_edge_style)

    # Warehouse 3D.
    view3d = b.add_vertex(root, value="3D просмотр склада\n/3d/warehouse/<id>/", style=card_style, x=1180, y=1660, w=300, h=58)
    save_layout = b.add_vertex(root, value="Сохранить layout\n.../layout/save/", style=card_style, x=1940, y=1640, w=320, h=58)
    save_object = b.add_vertex(root, value="Сохранить объект\n.../object/save/", style=card_style, x=1940, y=1710, w=320, h=58)
    delete_object = b.add_vertex(root, value="Удалить объект\n.../object/<id>/delete/", style=card_style, x=2920, y=1710, w=300, h=58)

    b.add_edge(root, source=warehouse3d, target=view3d, style=edge_style)
    b.add_edge(root, source=view3d, target=save_layout, style=edge_style)
    b.add_edge(root, source=view3d, target=save_object, style=edge_style)
    b.add_edge(root, source=save_object, target=delete_object, style=edge_style)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(ET.tostring(mxfile, encoding="utf-8", xml_declaration=True))


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate UI navigation draw.io schema for WMS")
    parser.add_argument(
        "--output",
        default="2Диплом/Схема_пользовательского_интерфейса_WMS.drawio",
        help="Output draw.io path",
    )
    args = parser.parse_args()
    build_ui_navigation(Path(args.output))
    print(f"Generated: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
