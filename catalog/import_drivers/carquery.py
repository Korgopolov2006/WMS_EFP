"""
Драйвер импорта справочника ТС из CarQuery API.

Документация: https://www.carqueryapi.com/documentation/api-usage/
Эндпоинты:
  /api/0.3/?cmd=getMakes
  /api/0.3/?cmd=getModels&make=<id>&year=<year>

CarQuery отвечает в JSONP ради совместимости — оборачивает JSON в
?( ... ); — поэтому мы либо передаём callback=?, либо парсим вручную.
Здесь явно используем `&callback=?` и срезаем оборачивающие скобки.
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterable

import requests

from .base import VehicleEntry, VehicleImportDriver

logger = logging.getLogger(__name__)

API_URL_HTTPS = "https://www.carqueryapi.com/api/0.3/"
API_URL_HTTP = "http://www.carqueryapi.com/api/0.3/"


def _strip_jsonp(text: str) -> str:
    """`?( ... );` → `...`"""
    text = (text or "").strip()
    if text.startswith("?("):
        text = text[2:]
    if text.endswith(");"):
        text = text[:-2]
    elif text.endswith(")"):
        text = text[:-1]
    return text


class CarQueryDriver(VehicleImportDriver):
    name = "carquery"

    def __init__(
        self,
        *,
        client=None,
        rate_limit_sec: float = 0.3,
        timeout_sec: float = 15.0,
        verify_ssl: bool = True,
        use_http: bool = False,
    ):
        self._client = client or requests.Session()
        self._client.headers.update({
            "Referer": "https://www.carqueryapi.com/",
            "User-Agent": "WMS-Catalog-Import/1.0",
        })
        self.rate_limit_sec = max(0.0, rate_limit_sec)
        self.timeout_sec = timeout_sec
        self._verify_ssl = verify_ssl
        self._url = API_URL_HTTP if use_http else API_URL_HTTPS

    # ─── низкоуровневые HTTP вызовы ────────────────────────

    def _get(self, params: dict) -> dict:
        if self.rate_limit_sec:
            time.sleep(self.rate_limit_sec)
        params = {**params, "callback": "?"}
        resp = self._client.get(
            self._url, params=params,
            timeout=self.timeout_sec,
            verify=self._verify_ssl,
        )
        resp.raise_for_status()
        return json.loads(_strip_jsonp(resp.text))

    # ─── публичный API драйвера ────────────────────────────

    def list_makes(self) -> list[str]:
        data = self._get({"cmd": "getMakes"})
        items = data.get("Makes") or []
        return sorted({(m.get("make_id") or "").strip() for m in items if m.get("make_id")})

    def list_makes_full(self) -> list[dict]:
        """Возвращает полные карточки марок (для сопоставления make_id ↔ make_display)."""
        data = self._get({"cmd": "getMakes"})
        return data.get("Makes") or []

    def list_models(self, make_id: str, year: int) -> list[str]:
        data = self._get({"cmd": "getModels", "make": make_id, "year": str(year)})
        items = data.get("Models") or []
        # CarQuery возвращает {"model_name": "Mustang", ...}
        return sorted({(m.get("model_name") or "").strip() for m in items if m.get("model_name")})

    def iter_entries(
        self,
        *,
        year_from: int,
        year_to: int,
        makes: list[str] | None = None,
    ) -> Iterable[VehicleEntry]:
        makes_full = self.list_makes_full()
        # отфильтруем по запрошенным make_id (если задано)
        if makes:
            wanted = {m.lower() for m in makes}
            makes_full = [m for m in makes_full if (m.get("make_id") or "").lower() in wanted]

        # display_name → красивая «капитализация» бренда
        for make in makes_full:
            make_id = (make.get("make_id") or "").strip()
            make_display = (make.get("make_display") or make_id).strip()
            if not make_id:
                continue
            seen_models: set[str] = set()
            for year in range(year_from, year_to + 1):
                try:
                    models = self.list_models(make_id, year)
                except Exception as exc:
                    logger.warning("CarQuery models %s/%s failed: %s", make_id, year, exc)
                    continue
                for model_name in models:
                    if model_name in seen_models:
                        continue
                    seen_models.add(model_name)
                    yield VehicleEntry(make_name=make_display, model_name=model_name)
