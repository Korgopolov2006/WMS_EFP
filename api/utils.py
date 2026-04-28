from __future__ import annotations

import json
from typing import Any

from django.http import HttpRequest, JsonResponse


def json_error(message: str, *, status: int = 400, code: str | None = None):
    payload = {"ok": False, "error": {"message": message}}
    if code:
        payload["error"]["code"] = code
    return JsonResponse(payload, status=status)


def json_ok(data, *, status: int = 200):
    return JsonResponse({"ok": True, "data": data}, status=status)


def paginate(request, qs, *, default_limit: int = 50, max_limit: int = 200):
    try:
        limit = int(request.GET.get("limit", default_limit))
    except ValueError:
        limit = default_limit
    try:
        offset = int(request.GET.get("offset", 0))
    except ValueError:
        offset = 0

    limit = max(1, min(limit, max_limit))
    offset = max(0, offset)

    total = qs.count()
    items = list(qs[offset : offset + limit])
    return items, {"limit": limit, "offset": offset, "total": total}


def parse_json(request: HttpRequest) -> dict[str, Any]:
    if request.content_type not in ("application/json", "application/json; charset=utf-8"):
        raise ValueError("Content-Type must be application/json")
    try:
        body = request.body.decode("utf-8")
        return json.loads(body or "{}")
    except json.JSONDecodeError as e:
        raise ValueError("Invalid JSON body") from e

