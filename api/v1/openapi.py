from __future__ import annotations

import re

from django.core.exceptions import DisallowedHost


_PATH_PARAM_RE = re.compile(r"<(?:(?P<converter>\w+):)?(?P<name>\w+)>")


QUERY_PARAMS = {
    "q": {
        "name": "q",
        "in": "query",
        "required": False,
        "schema": {"type": "string"},
        "description": "Текстовый поиск.",
    },
    "limit": {
        "name": "limit",
        "in": "query",
        "required": False,
        "schema": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
        "description": "Размер страницы.",
    },
    "offset": {
        "name": "offset",
        "in": "query",
        "required": False,
        "schema": {"type": "integer", "minimum": 0, "default": 0},
        "description": "Смещение.",
    },
    "status": {
        "name": "status",
        "in": "query",
        "required": False,
        "schema": {"type": "string"},
        "description": "Фильтр по статусу.",
    },
    "type": {
        "name": "type",
        "in": "query",
        "required": False,
        "schema": {"type": "string"},
        "description": "Фильтр по типу.",
    },
    "priority": {
        "name": "priority",
        "in": "query",
        "required": False,
        "schema": {"type": "string"},
        "description": "Фильтр по приоритету.",
    },
    "assigned_to": {
        "name": "assigned_to",
        "in": "query",
        "required": False,
        "schema": {"type": "integer"},
        "description": "ID назначенного пользователя.",
    },
    "period": {
        "name": "period",
        "in": "query",
        "required": False,
        "schema": {"type": "integer"},
        "description": "Период (дней).",
    },
    "forecast_days": {
        "name": "forecast_days",
        "in": "query",
        "required": False,
        "schema": {"type": "integer"},
        "description": "Горизонт прогноза (дней).",
    },
    "days": {
        "name": "days",
        "in": "query",
        "required": False,
        "schema": {"type": "integer"},
        "description": "Порог дней без движения.",
    },
    "role": {
        "name": "role",
        "in": "query",
        "required": False,
        "schema": {"type": "string"},
        "description": "Код роли.",
    },
    "order_id": {
        "name": "order_id",
        "in": "query",
        "required": False,
        "schema": {"type": "integer"},
        "description": "ID заказа.",
    },
    "zone_type": {
        "name": "zone_type",
        "in": "query",
        "required": False,
        "schema": {"type": "string"},
        "description": "Тип зоны (CELL/SHELF/FLOOR).",
    },
    "product_id": {
        "name": "product_id",
        "in": "query",
        "required": False,
        "schema": {"type": "integer"},
        "description": "ID товара.",
    },
    "location_id": {
        "name": "location_id",
        "in": "query",
        "required": False,
        "schema": {"type": "integer"},
        "description": "ID места хранения.",
    },
    "make_id": {
        "name": "make_id",
        "in": "query",
        "required": False,
        "schema": {"type": "integer"},
        "description": "ID марки ТС.",
    },
    "brand_id": {
        "name": "brand_id",
        "in": "query",
        "required": False,
        "schema": {"type": "integer"},
        "description": "ID бренда.",
    },
    "category_id": {
        "name": "category_id",
        "in": "query",
        "required": False,
        "schema": {"type": "integer"},
        "description": "ID категории.",
    },
    "sku": {
        "name": "sku",
        "in": "query",
        "required": False,
        "schema": {"type": "string"},
        "description": "Поиск по внутреннему артикулу.",
    },
    "oem": {
        "name": "oem",
        "in": "query",
        "required": False,
        "schema": {"type": "string"},
        "description": "Поиск по OEM.",
    },
    "qty": {
        "name": "qty",
        "in": "query",
        "required": False,
        "schema": {"type": "integer"},
        "description": "Количество (шт).",
    },
}


ROUTE_META = {
    "api_v1_health": {"methods": ["GET"], "tag": "system", "summary": "Проверка состояния API"},
    "api_v1_me": {"methods": ["GET"], "tag": "system", "summary": "Профиль API-пользователя"},
    "api_v1_dashboard_summary": {"methods": ["GET"], "tag": "system", "summary": "Сводка дашборда"},
    "api_v1_manual": {"methods": ["GET"], "tag": "system", "summary": "Справочная структура manual"},
    "api_v1_brands_list": {"methods": ["GET"], "tag": "catalog", "summary": "Список брендов", "query": ["q", "limit", "offset"]},
    "api_v1_categories_list": {
        "methods": ["GET"],
        "tag": "catalog",
        "summary": "Список категорий",
        "query": ["q", "limit", "offset"],
    },
    "api_v1_vehicle_makes_list": {
        "methods": ["GET"],
        "tag": "catalog",
        "summary": "Список марок ТС",
        "query": ["q", "limit", "offset"],
    },
    "api_v1_vehicle_models_list": {
        "methods": ["GET"],
        "tag": "catalog",
        "summary": "Список моделей ТС",
        "query": ["q", "make_id", "limit", "offset"],
    },
    "api_v1_warehouses_list": {
        "methods": ["GET"],
        "tag": "warehouse",
        "summary": "Список складов",
        "query": ["q", "limit", "offset"],
    },
    "api_v1_warehouse_map": {
        "methods": ["GET"],
        "tag": "warehouse",
        "summary": "Карта зон и мест хранения склада",
        "query": ["q", "limit", "offset"],
    },
    "api_v1_warehouse_objects": {
        "methods": ["GET"],
        "tag": "warehouse",
        "summary": "3D-объекты склада",
        "query": ["q", "limit", "offset"],
    },
    "api_v1_products_list": {
        "methods": ["GET", "POST"],
        "tag": "catalog",
        "summary": "Список/создание товаров",
        "query": ["q", "sku", "oem", "brand_id", "category_id", "limit", "offset"],
    },
    "api_v1_product_detail": {"methods": ["GET", "PUT", "PATCH", "DELETE"], "tag": "catalog", "summary": "Карточка товара"},
    "api_v1_product_xrefs_list": {
        "methods": ["GET"],
        "tag": "catalog",
        "summary": "Связи OEM/аналогов",
        "query": ["q", "limit", "offset"],
    },
    "api_v1_receivings_list": {
        "methods": ["GET", "POST"],
        "tag": "receiving",
        "summary": "Список/создание приёмок",
        "query": ["q", "status", "limit", "offset"],
    },
    "api_v1_receiving_detail": {"methods": ["GET", "PUT", "PATCH"], "tag": "receiving", "summary": "Документ приёмки"},
    "api_v1_receiving_lines": {
        "methods": ["GET", "POST"],
        "tag": "receiving",
        "summary": "Строки приёмки",
        "query": ["q", "limit", "offset"],
    },
    "api_v1_receiving_scan": {"methods": ["POST"], "tag": "receiving", "summary": "Сканирование в приёмке"},
    "api_v1_receiving_action": {"methods": ["POST"], "tag": "receiving", "summary": "Действие с приёмкой"},
    "api_v1_stock_list": {
        "methods": ["GET"],
        "tag": "inventory",
        "summary": "Список остатков",
        "query": ["q", "product_id", "location_id", "limit", "offset"],
    },
    "api_v1_stock_analogs": {"methods": ["GET"], "tag": "inventory", "summary": "Аналоги на остатках", "query": ["qty"]},
    "api_v1_inventories_list": {
        "methods": ["GET", "POST"],
        "tag": "inventory",
        "summary": "Список/создание инвентаризаций",
        "query": ["q", "status", "limit", "offset"],
    },
    "api_v1_inventory_detail": {"methods": ["GET", "PUT", "PATCH"], "tag": "inventory", "summary": "Документ инвентаризации"},
    "api_v1_inventory_lines": {
        "methods": ["GET", "POST"],
        "tag": "inventory",
        "summary": "Строки инвентаризации",
        "query": ["q", "limit", "offset"],
    },
    "api_v1_inventory_action": {"methods": ["POST"], "tag": "inventory", "summary": "Действие с инвентаризацией"},
    "api_v1_tasks": {
        "methods": ["GET", "POST"],
        "tag": "tasks",
        "summary": "Список/создание задач",
        "query": ["q", "type", "status", "priority", "assigned_to", "limit", "offset"],
    },
    "api_v1_task_detail": {"methods": ["GET", "PUT", "PATCH", "DELETE"], "tag": "tasks", "summary": "Карточка задачи"},
    "api_v1_task_action": {"methods": ["POST"], "tag": "tasks", "summary": "Действие с задачей"},
    "api_v1_task_comments": {
        "methods": ["GET", "POST"],
        "tag": "tasks",
        "summary": "Комментарии задачи",
        "query": ["limit", "offset"],
    },
    "api_v1_tasks_monitoring": {"methods": ["GET"], "tag": "tasks", "summary": "Сводка мониторинга задач"},
    "api_v1_orders_list_create": {
        "methods": ["GET", "POST"],
        "tag": "orders",
        "summary": "Список/создание заказов",
        "query": ["q", "status", "limit", "offset"],
    },
    "api_v1_order_detail_update": {"methods": ["GET", "PUT", "PATCH"], "tag": "orders", "summary": "Карточка заказа"},
    "api_v1_order_lines_list_create": {
        "methods": ["GET", "POST"],
        "tag": "orders",
        "summary": "Строки заказа",
        "query": ["q", "limit", "offset"],
    },
    "api_v1_order_action": {"methods": ["POST"], "tag": "orders", "summary": "Действие с заказом"},
    "api_v1_picking_tasks_list": {
        "methods": ["GET"],
        "tag": "picking",
        "summary": "Список задач подбора",
        "query": ["q", "status", "zone_type", "order_id", "limit", "offset"],
    },
    "api_v1_picking_task_detail": {"methods": ["GET", "PUT", "PATCH"], "tag": "picking", "summary": "Карточка задачи подбора"},
    "api_v1_picking_task_lines": {
        "methods": ["GET", "POST"],
        "tag": "picking",
        "summary": "Строки подбора",
        "query": ["q", "limit", "offset"],
    },
    "api_v1_picking_task_action": {"methods": ["POST"], "tag": "picking", "summary": "Действие с задачей подбора"},
    "api_v1_reports_abc_xyz": {
        "methods": ["GET"],
        "tag": "reports",
        "summary": "Отчет ABC-XYZ",
        "query": ["period", "q", "limit", "offset"],
    },
    "api_v1_reports_dead_stock": {
        "methods": ["GET"],
        "tag": "reports",
        "summary": "Отчет по мертвым остаткам",
        "query": ["days", "q", "limit", "offset"],
    },
    "api_v1_reports_analogs_vs_originals": {
        "methods": ["GET"],
        "tag": "reports",
        "summary": "Отчет аналоги vs оригиналы",
        "query": ["period", "q", "limit", "offset"],
    },
    "api_v1_reports_picking_errors": {
        "methods": ["GET"],
        "tag": "reports",
        "summary": "Отчет по ошибкам подбора",
        "query": ["period", "q", "limit", "offset"],
    },
    "api_v1_reports_demand_forecast": {
        "methods": ["GET"],
        "tag": "reports",
        "summary": "Отчет прогноз спроса",
        "query": ["period", "forecast_days", "q", "limit", "offset"],
    },
    "api_v1_reports_staff_efficiency": {
        "methods": ["GET"],
        "tag": "reports",
        "summary": "Отчет эффективность сотрудников",
        "query": ["period", "role", "q", "limit", "offset"],
    },
}


def _path_to_openapi(path_value: str) -> str:
    clean = path_value.lstrip("^").rstrip("$")
    clean = _PATH_PARAM_RE.sub(lambda m: "{" + m.group("name") + "}", clean)
    if not clean.startswith("/"):
        clean = "/" + clean
    return "/api/v1" + clean


def _extract_path_params(path_value: str):
    params = []
    for match in _PATH_PARAM_RE.finditer(path_value):
        converter = match.group("converter") or "str"
        name = match.group("name")
        schema_type = "integer" if converter == "int" else "string"
        params.append(
            {
                "name": name,
                "in": "path",
                "required": True,
                "schema": {"type": schema_type},
                "description": f"Path parameter: {name}",
            }
        )
    return params


def build_openapi_spec(urlpatterns, request):
    try:
        host = request.get_host()
    except DisallowedHost:
        host = request.META.get("HTTP_HOST") or "127.0.0.1:8000"
    scheme = "https" if request.is_secure() else "http"

    spec = {
        "openapi": "3.0.3",
        "info": {
            "title": "WMS API",
            "version": "1.0.0",
            "description": "API для WMS: каталог, приемка, инвентаризация, заказы, подбор, задачи, отчеты.",
        },
        "servers": [{"url": f"{scheme}://{host}"}],
        "components": {
            "securitySchemes": {
                "BearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "Token",
                    "description": "Authorization: Bearer <token>",
                }
            }
        },
        "security": [{"BearerAuth": []}],
        "paths": {},
        "tags": [],
    }

    tags_used = set()

    for pattern in urlpatterns:
        name = pattern.name
        if not name or name not in ROUTE_META:
            continue

        meta = ROUTE_META[name]
        path_value = str(pattern.pattern)
        openapi_path = _path_to_openapi(path_value)
        path_parameters = _extract_path_params(path_value)
        operations = spec["paths"].setdefault(openapi_path, {})

        tag = meta["tag"]
        tags_used.add(tag)

        query_parameters = [QUERY_PARAMS[q_name] for q_name in meta.get("query", []) if q_name in QUERY_PARAMS]

        for method in meta["methods"]:
            method_lc = method.lower()
            operation = {
                "tags": [tag],
                "summary": meta["summary"],
                "operationId": f"{name}_{method_lc}",
                "security": [{"BearerAuth": []}],
                "responses": {
                    "200": {"description": "Success"},
                    "400": {"description": "Validation error"},
                    "401": {"description": "Unauthorized"},
                    "404": {"description": "Not found"},
                },
                "parameters": path_parameters + (query_parameters if method == "GET" else []),
            }

            if method in ("POST", "PUT", "PATCH") and "action" not in openapi_path:
                operation["requestBody"] = {
                    "required": False,
                    "content": {
                        "application/json": {
                            "schema": {"type": "object", "additionalProperties": True}
                        }
                    },
                }

            operations[method_lc] = operation

    spec["tags"] = [{"name": tag} for tag in sorted(tags_used)]
    return spec
