from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET


ROOT_DIR = Path(__file__).resolve().parents[1]
APP_DIRS = [
    "accounts",
    "api",
    "catalog",
    "core",
    "efp",
    "inventory",
    "picking",
    "receiving",
    "reports",
    "tasks",
    "warehouse_3d",
    "wms",
]


@dataclass
class Relation:
    target_ref: str
    rel_type: str
    label: str = ""


@dataclass
class ClassInfo:
    class_id: str
    name: str
    app: str
    module: str
    file_path: Path
    kind: str
    bases: list[str] = field(default_factory=list)
    attributes: list[str] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)
    form_model_ref: str | None = None
    admin_model_refs: list[str] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)


@dataclass
class EdgeInfo:
    source_id: str
    target_id: str
    edge_type: str
    label: str = ""


def _module_from_path(path: Path) -> str:
    rel = path.relative_to(ROOT_DIR)
    return ".".join(rel.with_suffix("").parts)


def _expr_to_name(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _expr_to_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Subscript):
        return _expr_to_name(node.value)
    if isinstance(node, ast.Call):
        return _expr_to_name(node.func)
    return None


def _kind_for_file(path: Path) -> str:
    rel = path.relative_to(ROOT_DIR).as_posix()
    name = path.name
    if "/management/commands/" in rel:
        return "command"
    if name == "models.py":
        return "model"
    if name == "forms.py":
        return "form"
    if name == "services.py":
        return "service"
    if name in {"admin.py", "admin_mixins.py"}:
        return "admin"
    if name == "apps.py":
        return "config"
    if name == "auth.py":
        return "auth"
    if name == "constants.py":
        return "constant"
    if name == "views.py":
        return "view"
    if name == "views_api.py":
        return "api_view"
    if name == "docs.py":
        return "doc"
    if name == "openapi.py":
        return "doc"
    return "misc"


def _field_call_kind(call_name: str | None) -> str | None:
    if not call_name:
        return None
    short = call_name.split(".")[-1]
    if short == "ForeignKey":
        return "fk"
    if short == "OneToOneField":
        return "o2o"
    if short == "ManyToManyField":
        return "m2m"
    return None


def _format_attr(attr_name: str, call_name: str | None) -> str:
    if not call_name:
        return attr_name
    short = call_name.split(".")[-1]
    return f"{attr_name}: {short}"


def _extract_model_target(call: ast.Call) -> str | None:
    target_expr: ast.AST | None = None
    if call.args:
        target_expr = call.args[0]
    for kw in call.keywords:
        if kw.arg == "to":
            target_expr = kw.value
            break
    name = _expr_to_name(target_expr)
    if name == "settings.AUTH_USER_MODEL":
        return "User"
    return name


def _extract_form_model_ref(class_node: ast.ClassDef) -> str | None:
    for stmt in class_node.body:
        if not isinstance(stmt, ast.ClassDef) or stmt.name != "Meta":
            continue
        for child in stmt.body:
            if not isinstance(child, ast.Assign):
                continue
            for target in child.targets:
                if isinstance(target, ast.Name) and target.id == "model":
                    return _expr_to_name(child.value)
    return None


def _extract_admin_model_refs(class_node: ast.ClassDef) -> list[str]:
    refs: list[str] = []
    for stmt in class_node.body:
        if isinstance(stmt, ast.Assign):
            for t in stmt.targets:
                if isinstance(t, ast.Name) and t.id == "model":
                    ref = _expr_to_name(stmt.value)
                    if ref:
                        refs.append(ref)
    for deco in class_node.decorator_list:
        if isinstance(deco, ast.Call):
            dname = _expr_to_name(deco.func)
            if dname and dname.endswith("register"):
                for arg in deco.args:
                    ref = _expr_to_name(arg)
                    if ref:
                        refs.append(ref)
    return refs


def _iter_python_files() -> Iterable[Path]:
    for app in APP_DIRS:
        base = ROOT_DIR / app
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            rel = path.relative_to(ROOT_DIR).as_posix()
            if "/migrations/" in rel:
                continue
            if path.name.startswith("test") or path.name.endswith("_test.py"):
                continue
            yield path


def collect_classes() -> list[ClassInfo]:
    classes: list[ClassInfo] = []
    for path in _iter_python_files():
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        rel = path.relative_to(ROOT_DIR)
        app = rel.parts[0]
        module = _module_from_path(path)
        kind = _kind_for_file(path)

        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue

            class_id = f"{module}:{node.name}"
            info = ClassInfo(
                class_id=class_id,
                name=node.name,
                app=app,
                module=module,
                file_path=path,
                kind=kind,
            )

            info.bases = [_expr_to_name(base) or "UnknownBase" for base in node.bases]
            info.form_model_ref = _extract_form_model_ref(node) if kind == "form" else None
            info.admin_model_refs = _extract_admin_model_refs(node) if kind == "admin" else []
            info.decorators = [_expr_to_name(d) or "" for d in node.decorator_list]

            for stmt in node.body:
                if isinstance(stmt, ast.FunctionDef):
                    info.methods.append(stmt.name)
                    continue
                if isinstance(stmt, ast.AsyncFunctionDef):
                    info.methods.append(stmt.name)
                    continue

                if isinstance(stmt, ast.Assign):
                    call_name = _expr_to_name(stmt.value) if isinstance(stmt.value, ast.Call) else None
                    for target in stmt.targets:
                        if not isinstance(target, ast.Name):
                            continue
                        attr_name = target.id
                        info.attributes.append(_format_attr(attr_name, call_name))

                        if kind == "model" and isinstance(stmt.value, ast.Call):
                            rel_kind = _field_call_kind(call_name)
                            if rel_kind:
                                target_ref = _extract_model_target(stmt.value)
                                if target_ref:
                                    info.relations.append(
                                        Relation(
                                            target_ref=target_ref,
                                            rel_type=rel_kind,
                                            label=attr_name,
                                        )
                                    )
                    continue

                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    info.attributes.append(stmt.target.id)

            classes.append(info)
    return classes


def _resolve_ref(ref: str | None, source: ClassInfo, classes: list[ClassInfo]) -> str | None:
    if not ref:
        return None
    clean = ref.strip("'\"")
    if clean == "self":
        clean = source.name
    if clean == "settings.AUTH_USER_MODEL":
        clean = "User"

    name_only = clean.split(".")[-1]

    same_module = [c for c in classes if c.module == source.module and c.name == name_only]
    if same_module:
        return same_module[0].class_id

    same_app = [c for c in classes if c.app == source.app and c.name == name_only]
    if len(same_app) == 1:
        return same_app[0].class_id

    if "." in clean:
        module_guess = clean.rsplit(".", 1)[0]
        direct = [c for c in classes if c.module.endswith(module_guess) and c.name == name_only]
        if len(direct) == 1:
            return direct[0].class_id

    global_matches = [c for c in classes if c.name == name_only]
    if len(global_matches) == 1:
        return global_matches[0].class_id

    # Prefer model class when ambiguous.
    model_matches = [c for c in global_matches if c.kind == "model"]
    if len(model_matches) == 1:
        return model_matches[0].class_id

    return None


def build_edges(classes: list[ClassInfo]) -> list[EdgeInfo]:
    edges: list[EdgeInfo] = []
    seen: set[tuple[str, str, str, str]] = set()

    def add_edge(source_id: str, target_id: str, edge_type: str, label: str = "") -> None:
        if source_id == target_id:
            return
        key = (source_id, target_id, edge_type, label)
        if key in seen:
            return
        seen.add(key)
        edges.append(EdgeInfo(source_id=source_id, target_id=target_id, edge_type=edge_type, label=label))

    for cls in classes:
        for base in cls.bases:
            target = _resolve_ref(base, cls, classes)
            if target:
                add_edge(cls.class_id, target, "inheritance")

        for rel in cls.relations:
            target = _resolve_ref(rel.target_ref, cls, classes)
            if not target:
                continue
            if rel.rel_type == "fk":
                add_edge(cls.class_id, target, "fk", f"{rel.label} (1..*)")
            elif rel.rel_type == "o2o":
                add_edge(cls.class_id, target, "o2o", f"{rel.label} (1..1)")
            elif rel.rel_type == "m2m":
                add_edge(cls.class_id, target, "m2m", f"{rel.label} (*..*)")

        if cls.form_model_ref:
            target = _resolve_ref(cls.form_model_ref, cls, classes)
            if target:
                add_edge(cls.class_id, target, "form_model", "Meta.model")

        for ref in cls.admin_model_refs:
            target = _resolve_ref(ref, cls, classes)
            if target:
                add_edge(cls.class_id, target, "admin_model", "admin")

    return edges


def _class_lines(cls: ClassInfo, max_attrs: int = 14, max_methods: int = 12) -> list[str]:
    lines: list[str] = []
    lines.append(f"&lt;&lt;{cls.kind}&gt;&gt;")
    lines.append(f"{cls.module}")

    attrs = cls.attributes[:max_attrs]
    methods = cls.methods[:max_methods]
    if attrs:
        lines.append("---")
        lines.extend([f"+ {a}" for a in attrs])
        if len(cls.attributes) > max_attrs:
            lines.append("+ ...")
    if methods:
        lines.append("---")
        lines.extend([f"+ {m}()" for m in methods])
        if len(cls.methods) > max_methods:
            lines.append("+ ...")
    return lines


def _style_for_kind(kind: str) -> str:
    palette = {
        "model": ("#E8F5E9", "#2E7D32"),
        "form": ("#E3F2FD", "#1565C0"),
        "service": ("#FFF3E0", "#E65100"),
        "view": ("#F3E5F5", "#6A1B9A"),
        "api_view": ("#F3E5F5", "#6A1B9A"),
        "admin": ("#FCE4EC", "#AD1457"),
        "config": ("#E0F2F1", "#00695C"),
        "auth": ("#EDE7F6", "#4527A0"),
        "constant": ("#F9FBE7", "#827717"),
        "command": ("#ECEFF1", "#455A64"),
        "doc": ("#E1F5FE", "#0277BD"),
        "misc": ("#F5F5F5", "#616161"),
    }
    fill, stroke = palette.get(kind, ("#F5F5F5", "#616161"))
    return (
        "rounded=0;whiteSpace=wrap;html=1;"
        f"fillColor={fill};strokeColor={stroke};fontColor=#1f1f1f;"
        "align=left;verticalAlign=top;spacing=6;fontSize=11;"
    )


def _container_style() -> str:
    return (
        "rounded=1;whiteSpace=wrap;html=1;"
        "fillColor=#fafafa;strokeColor=#c7c7c7;"
        "align=left;verticalAlign=top;spacing=8;fontStyle=1;"
    )


def _header_style() -> str:
    return (
        "rounded=1;whiteSpace=wrap;html=1;"
        "fillColor=#eeeeee;strokeColor=#9e9e9e;"
        "align=center;verticalAlign=middle;fontStyle=1;fontSize=13;"
    )


def _inheritance_edge_style() -> str:
    return (
        "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
        "endArrow=block;endFill=0;strokeColor=#1f4e79;strokeWidth=1.2;"
    )


def _assoc_edge_style(dashed: bool = False, color: str = "#5f6368") -> str:
    style = (
        "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
        f"endArrow=open;endFill=0;strokeColor={color};strokeWidth=1.1;fontSize=10;"
    )
    if dashed:
        style += "dashed=1;dashPattern=6 4;"
    return style


def _edge_style(edge_type: str) -> str:
    if edge_type == "inheritance":
        return _inheritance_edge_style()
    if edge_type == "m2m":
        return _assoc_edge_style(dashed=True, color="#7b1fa2")
    if edge_type == "o2o":
        return _assoc_edge_style(dashed=False, color="#00897b")
    if edge_type == "form_model":
        return _assoc_edge_style(dashed=True, color="#1976d2")
    if edge_type == "admin_model":
        return _assoc_edge_style(dashed=True, color="#ad1457")
    return _assoc_edge_style(dashed=False, color="#455a64")


def build_drawio(classes: list[ClassInfo], edges: list[EdgeInfo], output: Path) -> None:
    app_order = [
        "accounts",
        "api",
        "catalog",
        "receiving",
        "inventory",
        "picking",
        "tasks",
        "reports",
        "warehouse_3d",
        "core",
        "efp",
        "wms",
    ]
    app_classes: dict[str, list[ClassInfo]] = {app: [] for app in app_order}
    for cls in classes:
        app_classes.setdefault(cls.app, []).append(cls)

    kind_order = {
        "model": 0,
        "form": 1,
        "service": 2,
        "view": 3,
        "api_view": 3,
        "admin": 4,
        "auth": 5,
        "constant": 6,
        "config": 7,
        "command": 8,
        "doc": 9,
        "misc": 10,
    }
    for app in app_classes:
        app_classes[app].sort(key=lambda c: (kind_order.get(c.kind, 99), c.name))

    # Pre-calc layout heights.
    col_w = 440
    col_step = 560
    x0 = 40
    y_header = 40
    y_start = 120
    node_w = 420
    node_gap = 16
    min_h = 84
    line_h = 15

    class_rects: dict[str, tuple[float, float, float, float]] = {}
    column_bounds: dict[str, tuple[float, float, float, float]] = {}
    class_lines: dict[str, list[str]] = {}

    ordered_apps = [a for a in app_order if app_classes.get(a)] + sorted(a for a in app_classes if a not in app_order and app_classes[a])

    max_bottom = 0.0
    for col_idx, app in enumerate(ordered_apps):
        x = x0 + col_idx * col_step
        y = y_start
        for cls in app_classes[app]:
            lines = _class_lines(cls)
            class_lines[cls.class_id] = lines
            h = max(min_h, 36 + len(lines) * line_h)
            class_rects[cls.class_id] = (x + 10, y, node_w, h)
            y += h + node_gap
        col_h = max(180, y - y_start + 20)
        column_bounds[app] = (x, y_header, col_w, col_h + 72)
        max_bottom = max(max_bottom, y_header + col_h + 72)

    page_w = int(x0 + len(ordered_apps) * col_step + 120)
    page_h = int(max_bottom + 600)

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
        {
            "name": "Class Diagram WMS",
            "id": "wms-class-diagram",
        },
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
            "pageWidth": str(page_w),
            "pageHeight": str(page_h),
            "math": "0",
            "shadow": "0",
        },
    )
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    next_id = 2

    def add_vertex(value: str, style: str, x: float, y: float, w: float, h: float) -> str:
        nonlocal next_id
        cid = str(next_id)
        next_id += 1
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
                "x": f"{x:.2f}",
                "y": f"{y:.2f}",
                "width": f"{w:.2f}",
                "height": f"{h:.2f}",
                "as": "geometry",
            },
        )
        return cid

    def add_edge(source: str, target: str, style: str, label: str = "", points: list[tuple[float, float]] | None = None) -> None:
        nonlocal next_id
        cid = str(next_id)
        next_id += 1
        edge = ET.SubElement(
            root,
            "mxCell",
            {
                "id": cid,
                "value": label,
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
            for px, py in points:
                ET.SubElement(arr, "mxPoint", {"x": f"{px:.2f}", "y": f"{py:.2f}"})

    app_header_ids: dict[str, str] = {}
    class_cell_ids: dict[str, str] = {}

    # Draw columns.
    for app in ordered_apps:
        x, y, w, h = column_bounds[app]
        add_vertex("", _container_style(), x, y, w, h)
        app_header_ids[app] = add_vertex(app, _header_style(), x + 10, y + 10, w - 20, 40)
        for cls in app_classes[app]:
            cx, cy, cw, ch = class_rects[cls.class_id]
            lines = class_lines[cls.class_id]
            value = f"<b>{cls.name}</b><br/>" + "<br/>".join(lines)
            class_cell_ids[cls.class_id] = add_vertex(value, _style_for_kind(cls.kind), cx, cy, cw, ch)

    # Class helpers.
    class_col_index = {app: idx for idx, app in enumerate(ordered_apps)}
    top_corridor_base = 70.0
    bottom_corridor_base = max_bottom + 80.0
    top_lane = 0
    bottom_lane = 0
    local_lane: dict[int, int] = {}

    def rect_for(class_id: str) -> tuple[float, float, float, float]:
        return class_rects[class_id]

    def center_y(class_id: str) -> float:
        x, y, w, h = rect_for(class_id)
        return y + h / 2.0

    for edge in sorted(edges, key=lambda e: (e.edge_type, e.source_id, e.target_id)):
        if edge.source_id not in class_cell_ids or edge.target_id not in class_cell_ids:
            continue

        s = classes_by_id[edge.source_id]
        t = classes_by_id[edge.target_id]
        sx, sy, sw, sh = rect_for(s.class_id)
        tx, ty, tw, th = rect_for(t.class_id)
        syc = sy + sh / 2.0
        tyc = ty + th / 2.0

        s_col = class_col_index.get(s.app, 0)
        t_col = class_col_index.get(t.app, 0)
        points: list[tuple[float, float]] | None = None

        if s_col == t_col:
            lane_idx = local_lane.get(s_col, 0)
            local_lane[s_col] = lane_idx + 1
            side_right = lane_idx % 2 == 0
            # Keep same-column routes inside column gutters only.
            gx = sx + sw + 24.0 if side_right else sx - 24.0
            points = [(gx, syc), (gx, tyc)]
        else:
            go_right = tx > sx
            s_out = sx + sw + 20.0 if go_right else sx - 20.0
            t_out = tx - 20.0 if go_right else tx + tw + 20.0

            # Keep long cross-app edges outside class blocks.
            if syc + tyc > max_bottom:
                lane_y = bottom_corridor_base + bottom_lane * 12.0
                bottom_lane += 1
            else:
                lane_y = top_corridor_base - top_lane * 10.0
                top_lane += 1
            points = [(s_out, syc), (s_out, lane_y), (t_out, lane_y), (t_out, tyc)]

        add_edge(
            source=class_cell_ids[edge.source_id],
            target=class_cell_ids[edge.target_id],
            style=_edge_style(edge.edge_type),
            label=edge.label,
            points=points,
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(ET.tostring(mxfile, encoding="utf-8", xml_declaration=True))


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate class diagram (.drawio) from project Python classes.")
    parser.add_argument(
        "--output",
        default="2Диплом/Диаграмма_классов_WMS.drawio",
        help="Output .drawio file path",
    )
    args = parser.parse_args()

    classes = collect_classes()
    global classes_by_id
    classes_by_id = {c.class_id: c for c in classes}
    edges = build_edges(classes)
    build_drawio(classes, edges, Path(args.output))
    print(f"Classes: {len(classes)}")
    print(f"Edges: {len(edges)}")
    print(f"Generated: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
