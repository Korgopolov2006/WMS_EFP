from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from datetime import datetime, UTC
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import django


def _setup_django() -> None:
    import os

    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "wms.settings")
    django.setup()


def _clean_default(raw: str | None) -> str:
    if not raw:
        return ""
    value = raw.strip()
    value = re.sub(r"::[a-zA-Z0-9_ \[\]\.\"]+", "", value)
    value = value.replace("timezone('utc', now())", "now()")
    return value


def _format_type(col: dict[str, Any]) -> str:
    data_type = (col.get("data_type") or "").lower()
    char_len = col.get("char_len")
    num_prec = col.get("num_prec")
    num_scale = col.get("num_scale")

    if data_type == "character varying":
        return f"VARCHAR({char_len})" if char_len else "VARCHAR"
    if data_type == "character":
        return f"CHAR({char_len})" if char_len else "CHAR"
    if data_type == "text":
        return "TEXT"
    if data_type == "bigint":
        return "BIGINT"
    if data_type == "integer":
        return "INT"
    if data_type == "smallint":
        return "SMALLINT"
    if data_type in {"boolean"}:
        return "BOOLEAN"
    if data_type in {"timestamp with time zone"}:
        return "TIMESTAMPTZ"
    if data_type in {"timestamp without time zone"}:
        return "TIMESTAMP"
    if data_type == "date":
        return "DATE"
    if data_type == "numeric":
        if num_prec and num_scale is not None:
            return f"DECIMAL({num_prec},{num_scale})"
        return "DECIMAL"
    if data_type == "double precision":
        return "DOUBLE"
    if data_type == "real":
        return "FLOAT"
    if data_type == "jsonb":
        return "JSONB"
    if data_type == "uuid":
        return "UUID"
    return (col.get("udt_name") or data_type or "UNKNOWN").upper()


def _table_group(table_name: str) -> str:
    if table_name.startswith("warehouse_3d_"):
        return "warehouse_3d"
    return table_name.split("_", 1)[0]


def _build_line(
    col: dict[str, Any],
    *,
    is_pk: bool,
    fk_ref: tuple[str, str] | None,
) -> str:
    prefix = "PK: " if is_pk else "FK: " if fk_ref else ""
    parts: list[str] = [_format_type(col)]

    if str(col.get("is_identity", "")).upper() == "YES":
        parts.append("AUTO_INCREMENT")

    if str(col.get("is_nullable", "")).upper() == "NO":
        parts.append("NOT NULL")
    else:
        parts.append("NULL")

    default_value = _clean_default(col.get("column_default"))
    if default_value and str(col.get("is_identity", "")).upper() != "YES":
        parts.append(f"DEFAULT {default_value}")

    return f"{prefix}{col['column_name']} ({' '.join(parts)})"


def _color_for_group(group: str) -> tuple[str, str]:
    palette = {
        "accounts": ("#8E44AD", "#6C3483"),
        "api": ("#16A085", "#117864"),
        "auth": ("#7F8C8D", "#616A6B"),
        "catalog": ("#F39C12", "#B9770E"),
        "django": ("#95A5A6", "#707B7C"),
        "inventory": ("#27AE60", "#1E8449"),
        "picking": ("#2E86DE", "#1F618D"),
        "receiving": ("#17A589", "#117A65"),
        "reports": ("#9B59B6", "#76448A"),
        "tasks": ("#E74C3C", "#B03A2E"),
        "warehouse_3d": ("#34495E", "#2C3E50"),
    }
    return palette.get(group, ("#607D8B", "#455A64"))


def _fetch_schema() -> tuple[dict[str, list[dict[str, Any]]], dict[str, set[str]], list[dict[str, str]]]:
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                c.table_name,
                c.column_name,
                c.ordinal_position,
                c.data_type,
                c.udt_name,
                c.character_maximum_length,
                c.numeric_precision,
                c.numeric_scale,
                c.is_nullable,
                c.column_default,
                c.is_identity,
                c.identity_generation
            FROM information_schema.columns c
            WHERE c.table_schema = 'public'
            ORDER BY c.table_name, c.ordinal_position
            """
        )
        column_rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT kcu.table_name, kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            WHERE tc.table_schema = 'public'
              AND tc.constraint_type = 'PRIMARY KEY'
            """
        )
        pk_rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT
                kcu.table_name,
                kcu.column_name,
                ccu.table_name AS ref_table,
                ccu.column_name AS ref_column,
                tc.constraint_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
              ON tc.constraint_name = ccu.constraint_name
             AND tc.table_schema = ccu.table_schema
            WHERE tc.table_schema = 'public'
              AND tc.constraint_type = 'FOREIGN KEY'
            ORDER BY kcu.table_name, kcu.column_name
            """
        )
        fk_rows = cursor.fetchall()

    columns_by_table: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in column_rows:
        columns_by_table[row[0]].append(
            {
                "table_name": row[0],
                "column_name": row[1],
                "ordinal_position": row[2],
                "data_type": row[3],
                "udt_name": row[4],
                "char_len": row[5],
                "num_prec": row[6],
                "num_scale": row[7],
                "is_nullable": row[8],
                "column_default": row[9],
                "is_identity": row[10],
                "identity_generation": row[11],
            }
        )

    pk_map: dict[str, set[str]] = defaultdict(set)
    for table_name, col_name in pk_rows:
        pk_map[table_name].add(col_name)

    fk_list: list[dict[str, str]] = []
    for table_name, col_name, ref_table, ref_column, constraint_name in fk_rows:
        fk_list.append(
            {
                "table": table_name,
                "column": col_name,
                "ref_table": ref_table,
                "ref_column": ref_column,
                "constraint": constraint_name,
            }
        )

    return dict(columns_by_table), dict(pk_map), fk_list


def _add_diagram(
    *,
    mxfile: ET.Element,
    page_name: str,
    page_id: str,
    tables: list[str],
    columns_by_table: dict[str, list[dict[str, Any]]],
    pk_map: dict[str, set[str]],
    fk_list: list[dict[str, str]],
) -> None:
    diagram = ET.SubElement(mxfile, "diagram", {"id": page_id, "name": page_name})
    model = ET.SubElement(
        diagram,
        "mxGraphModel",
        {
            "dx": "2400",
            "dy": "1400",
            "grid": "1",
            "gridSize": "10",
            "guides": "1",
            "tooltips": "1",
            "connect": "1",
            "arrows": "1",
            "fold": "1",
            "page": "1",
            "pageScale": "1",
            "pageWidth": "3000",
            "pageHeight": "2200",
            "math": "0",
            "shadow": "0",
        },
    )
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    tables_by_group: dict[str, list[str]] = defaultdict(list)
    for table in tables:
        tables_by_group[_table_group(table)].append(table)

    group_order = [
        "catalog",
        "receiving",
        "inventory",
        "picking",
        "tasks",
        "reports",
        "accounts",
        "api",
        "warehouse_3d",
        "auth",
        "django",
    ]
    ordered_groups = [group for group in group_order if group in tables_by_group] + sorted(
        g for g in tables_by_group if g not in group_order
    )

    next_id = 2
    table_cell_ids: dict[str, str] = {}

    col_x = 30
    col_width = 420
    col_gap = 44

    for group in ordered_groups:
        y = 34
        for table in sorted(tables_by_group[group]):
            table_id = str(next_id)
            next_id += 1

            fk_by_column = {
                fk["column"]: (fk["ref_table"], fk["ref_column"])
                for fk in fk_list
                if fk["table"] == table
            }

            lines: list[str] = []
            row_meta: list[tuple[bool, bool]] = []
            for col in columns_by_table.get(table, []):
                col_name = col["column_name"]
                is_pk = col_name in pk_map.get(table, set())
                is_fk = col_name in fk_by_column
                lines.append(
                    _build_line(
                        col,
                        is_pk=is_pk,
                        fk_ref=fk_by_column.get(col_name),
                    )
                )
                row_meta.append((is_pk, is_fk))

            row_h = 30
            header_h = 40
            body_h = max(90, len(lines) * row_h)
            table_h = header_h + body_h

            header_color, stroke_color = _color_for_group(group)
            table_style = (
                "swimlane;fontStyle=1;childLayout=stackLayout;horizontal=1;"
                f"startSize={header_h};horizontalStack=0;resizeParent=1;resizeParentMax=0;"
                "resizeLast=0;collapsible=0;marginBottom=0;align=center;fontSize=16;"
                f"fillColor={header_color};strokeColor={stroke_color};fontColor=#ffffff;"
            )

            table_cell = ET.SubElement(
                root,
                "mxCell",
                {
                    "id": table_id,
                    "value": table,
                    "style": table_style,
                    "vertex": "1",
                    "parent": "1",
                },
            )
            ET.SubElement(
                table_cell,
                "mxGeometry",
                {
                    "x": str(col_x),
                    "y": str(y),
                    "width": str(col_width),
                    "height": str(table_h),
                    "as": "geometry",
                },
            )

            for idx, line in enumerate(lines):
                row_id = str(next_id)
                next_id += 1
                is_pk, is_fk = row_meta[idx]
                row_style = "text;strokeColor=none;fillColor=none;spacingLeft=8;align=left;fontSize=13;"
                if is_pk:
                    row_style += "fontStyle=1;"
                if is_fk:
                    row_style += "fontColor=#d35400;"
                row_cell = ET.SubElement(
                    root,
                    "mxCell",
                    {
                        "id": row_id,
                        "value": line,
                        "style": row_style,
                        "vertex": "1",
                        "parent": table_id,
                    },
                )
                ET.SubElement(
                    row_cell,
                    "mxGeometry",
                    {
                        "y": str(header_h + idx * row_h),
                        "width": str(col_width),
                        "height": str(row_h),
                        "as": "geometry",
                    },
                )

            table_cell_ids[table] = table_id
            y += table_h + 28

        col_x += col_width + col_gap

    edge_style = (
        "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
        "endArrow=none;strokeColor=#6E6E6E;strokeWidth=1;fontSize=10;"
    )
    for fk in fk_list:
        src = table_cell_ids.get(fk["table"])
        dst = table_cell_ids.get(fk["ref_table"])
        if not src or not dst:
            continue
        edge_id = str(next_id)
        next_id += 1
        edge = ET.SubElement(
            root,
            "mxCell",
            {
                "id": edge_id,
                "value": f"{fk['column']} -> {fk['ref_column']}",
                "style": edge_style,
                "edge": "1",
                "parent": "1",
                "source": src,
                "target": dst,
            },
        )
        ET.SubElement(edge, "mxGeometry", {"relative": "1", "as": "geometry"})


def build_drawio(output: Path) -> None:
    columns_by_table, pk_map, fk_list = _fetch_schema()
    all_tables = sorted(columns_by_table.keys())
    business_tables = [t for t in all_tables if _table_group(t) not in {"auth", "django"}]

    mxfile = ET.Element(
        "mxfile",
        {
            "host": "Electron",
            "modified": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) draw.io/28.2.8 Chrome/140.0.7339.240 Electron/38.4.0 Safari/537.36",
            "version": "28.2.8",
        },
    )

    _add_diagram(
        mxfile=mxfile,
        page_name="WMS Business",
        page_id="wms_business",
        tables=business_tables,
        columns_by_table=columns_by_table,
        pk_map=pk_map,
        fk_list=fk_list,
    )
    _add_diagram(
        mxfile=mxfile,
        page_name="WMS Full",
        page_id="wms_full",
        tables=all_tables,
        columns_by_table=columns_by_table,
        pk_map=pk_map,
        fk_list=fk_list,
    )

    xml_data = ET.tostring(mxfile, encoding="utf-8", xml_declaration=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(xml_data)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate draw.io ERD from current PostgreSQL schema.")
    parser.add_argument("--output", default="db/wms_erd.drawio", help="Output .drawio file path")
    args = parser.parse_args()

    _setup_django()
    build_drawio(Path(args.output))
    print(f"Generated: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
