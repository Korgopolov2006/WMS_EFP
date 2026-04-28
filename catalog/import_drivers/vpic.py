"""
Драйвер NHTSA vPIC API (https://vpic.nhtsa.dot.gov/api/).

Public domain (US Federal Government). Никаких лицензионных ограничений.
Чистый JSON, без callback/JSONP. Покрывает мировые марки и модели.

Эндпоинты:
  /vehicles/getallmakes?format=json
  /vehicles/GetModelsForMake/<MakeName>?format=json
  /vehicles/GetModelsForMakeYear/make/<Name>/modelyear/<YYYY>?format=json
"""
from __future__ import annotations

import logging
import time
from collections.abc import Iterable

import requests

from .base import VehicleEntry, VehicleImportDriver

logger = logging.getLogger(__name__)

API_ROOT = "https://vpic.nhtsa.dot.gov/api"


class VpicDriver(VehicleImportDriver):
    name = "vpic"

    def __init__(
        self,
        *,
        client=None,
        rate_limit_sec: float = 0.0,  # vPIC лимит мягкий
        timeout_sec: float = 15.0,
        verify_ssl: bool = True,
    ):
        self._client = client or requests.Session()
        self._client.headers.update({"User-Agent": "WMS-Catalog-Import/1.0"})
        self.rate_limit_sec = max(0.0, rate_limit_sec)
        self.timeout_sec = timeout_sec
        self._verify_ssl = verify_ssl

    def _get(self, path: str, params: dict | None = None) -> dict:
        if self.rate_limit_sec:
            time.sleep(self.rate_limit_sec)
        params = {**(params or {}), "format": "json"}
        resp = self._client.get(
            f"{API_ROOT}{path}", params=params,
            timeout=self.timeout_sec,
            verify=self._verify_ssl,
        )
        resp.raise_for_status()
        return resp.json()

    def list_makes(self) -> list[str]:
        data = self._get("/vehicles/getallmakes")
        return sorted({(r.get("Make_Name") or "").strip()
                       for r in (data.get("Results") or [])
                       if r.get("Make_Name")})

    def iter_entries(
        self,
        *,
        year_from: int,
        year_to: int,
        makes: list[str] | None = None,
    ) -> Iterable[VehicleEntry]:
        target_makes = makes if makes else self.list_makes()
        for make in target_makes:
            try:
                if year_from == year_to:
                    data = self._get(
                        f"/vehicles/GetModelsForMakeYear/make/{make}/modelyear/{year_from}"
                    )
                else:
                    # Для интервала годов делаем по году — vPIC считает год как фильтр
                    seen: set[str] = set()
                    for year in range(year_from, year_to + 1):
                        data = self._get(
                            f"/vehicles/GetModelsForMakeYear/make/{make}/modelyear/{year}"
                        )
                        for r in (data.get("Results") or []):
                            name = (r.get("Model_Name") or "").strip()
                            mk = (r.get("Make_Name") or make).strip()
                            if not name or name in seen:
                                continue
                            seen.add(name)
                            yield VehicleEntry(make_name=mk, model_name=name)
                    continue  # пропустить нижний цикл — мы уже выдали
            except Exception as exc:
                logger.warning("vPIC failed for make=%s: %s", make, exc)
                continue

            for r in (data.get("Results") or []):
                name = (r.get("Model_Name") or "").strip()
                mk = (r.get("Make_Name") or make).strip()
                if name:
                    yield VehicleEntry(make_name=mk, model_name=name)
