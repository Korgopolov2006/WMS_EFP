"""
Сервис для работы с сайтом EFP Parts (efp-parts.ru).
Поиск деталей по OEM коду.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from django.core.cache import cache

logger = logging.getLogger(__name__)


class EFPService:
    """Сервис для работы с EFP Parts API."""
    
    BASE_HOST = "efp-parts.ru"
    BASE_URL = "https://efp-parts.ru"
    SEARCH_URL = "https://efp-parts.ru/search"
    TIMEOUT = (3, 5)  # (connect, read) секунд
    SCHEMES = ("https", "http")
    SEARCH_CACHE_TTL_SUCCESS = 60 * 60 * 24  # 24 часа
    SEARCH_CACHE_TTL_NOT_FOUND = 60 * 60 * 12  # 12 часов
    SEARCH_CACHE_TTL_TRANSIENT = 60 * 15  # 15 минут

    @staticmethod
    def manual_search_url(oem_code: str) -> str:
        safe_code = quote((oem_code or "").strip())
        return f"http://{EFPService.BASE_HOST}/search?pcode={safe_code}"

    @staticmethod
    def _normalize_oem_code(oem_code: str | None) -> str:
        return (oem_code or "").strip().upper()

    @staticmethod
    def _cache_key_for_search(oem_code: str) -> str:
        return f"efp:search:{oem_code}"

    @staticmethod
    def _cache_ttl_for_error_code(error_code: str) -> int:
        if error_code == "ok":
            return EFPService.SEARCH_CACHE_TTL_SUCCESS
        if error_code == "not_found":
            return EFPService.SEARCH_CACHE_TTL_NOT_FOUND
        return EFPService.SEARCH_CACHE_TTL_TRANSIENT

    @staticmethod
    def _build_search_urls(oem_code: str) -> list[str]:
        safe_code = quote(oem_code.strip())
        return [f"{scheme}://{EFPService.BASE_HOST}/search?pcode={safe_code}" for scheme in EFPService.SCHEMES]

    @staticmethod
    def _build_detail_urls(url: str) -> list[str]:
        if not url:
            return []

        parsed = urlparse(url)
        if not parsed.netloc:
            absolute = urljoin(EFPService.BASE_URL, url)
            parsed = urlparse(absolute)

        urls: list[str] = []
        if parsed.netloc:
            for scheme in EFPService.SCHEMES:
                candidate = urlunparse((scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))
                if candidate not in urls:
                    urls.append(candidate)
        return urls

    @staticmethod
    def _check_access_denied(soup: BeautifulSoup, page_url: str) -> tuple[bool, str]:
        title_text = soup.title.get_text(" ", strip=True).lower() if soup.title else ""
        page_text = soup.get_text(" ", strip=True).lower()
        markers = [
            "доступ запрещ",
            "access denied",
            "пройти проверку браузера",
            "nodacdn",
        ]
        if not any(marker in title_text or marker in page_text for marker in markers):
            return False, ""

        check_link = soup.find("a", href=True, string=re.compile(r"проверку браузера|browser check", re.I))
        if not check_link:
            check_link = soup.find("a", href=True)
        check_url = urljoin(page_url, check_link["href"]) if check_link else ""
        message = "EFP отклоняет автоматический запрос (anti-bot). Откройте поиск вручную в браузере."
        if check_url:
            message += f" Проверка браузера: {check_url}"
        return True, message
    
    @staticmethod
    def search_part(oem_code: str, *, use_cache: bool = True) -> tuple[bool, list[dict], str, str]:
        """
        Поиск деталей по OEM коду на сайте EFP Parts.
        
        Args:
            oem_code: OEM код детали (число после pcode=)
            
        Returns:
            (success: bool, results: list[dict], message: str, error_code: str)
            
        Формат результата:
        {
            "name": "Название детали",
            "brand": "Бренд",
            "photo_url": "URL фото",
            "price": "Цена",
            "availability": "Наличие",
            "detail_url": "Ссылка на страницу детали",
            "oem": "OEM код"
        }
        """
        normalized_oem = EFPService._normalize_oem_code(oem_code)
        if not normalized_oem:
            return False, [], "OEM код не указан", "validation_error"

        if use_cache:
            cache_key = EFPService._cache_key_for_search(normalized_oem)
            cached = cache.get(cache_key)
            if isinstance(cached, dict):
                return (
                    bool(cached.get("success")),
                    list(cached.get("results") or []),
                    str(cached.get("message") or ""),
                    str(cached.get("error_code") or "ok"),
                )

        oem_code = normalized_oem
        network_errors: list[str] = []
        
        for search_url in EFPService._build_search_urls(oem_code):
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
                "Referer": f"http://{EFPService.BASE_HOST}/",
            }

            logger.info(f"Searching EFP Parts for OEM: {oem_code} via {search_url}")

            try:
                response = requests.get(search_url, headers=headers, timeout=EFPService.TIMEOUT, allow_redirects=True)
                response.raise_for_status()
            except requests.exceptions.Timeout:
                network_errors.append(f"timeout:{search_url}")
                logger.warning(f"EFP Parts timeout for OEM {oem_code} via {search_url}")
                continue
            except requests.exceptions.RequestException as e:
                network_errors.append(f"request_error:{search_url}:{e}")
                logger.warning(f"EFP Parts request error for OEM {oem_code} via {search_url}: {e}")
                continue

            soup = BeautifulSoup(response.text, "html.parser")
            denied, denied_message = EFPService._check_access_denied(soup, response.url)
            if denied:
                logger.warning(f"EFP access denied for OEM {oem_code} via {search_url}")
                payload = (False, [], denied_message, "access_denied")
                if use_cache:
                    cache.set(
                        EFPService._cache_key_for_search(normalized_oem),
                        {
                            "success": payload[0],
                            "results": payload[1],
                            "message": payload[2],
                            "error_code": payload[3],
                        },
                        timeout=EFPService._cache_ttl_for_error_code(payload[3]),
                    )
                return payload

            try:
                results = []

                # Ищем карточки товаров (адаптируем под структуру сайта EFP)
                # Обычно товары находятся в контейнерах с классом product, item, card и т.д.
                product_cards = soup.find_all(["div", "article"], class_=re.compile(r"product|item|card|goods", re.I))

                if not product_cards:
                    # Пробуем найти по другим селекторам
                    product_cards = soup.find_all("div", class_=re.compile(r"catalog|search", re.I))

                for card in product_cards[:10]:  # Ограничиваем до 10 результатов
                    try:
                        result = EFPService._parse_product_card(card, oem_code)
                        if result:
                            results.append(result)
                    except Exception as e:
                        logger.warning(f"Error parsing product card: {e}")
                        continue

                if not results:
                    # Если не нашли через карточки, пробуем найти основную информацию на странице
                    main_result = EFPService._parse_main_page(soup, oem_code)
                    if main_result:
                        results.append(main_result)

                if results:
                    payload = (True, results, f"Найдено {len(results)} деталей", "ok")
                    if use_cache:
                        cache.set(
                            EFPService._cache_key_for_search(normalized_oem),
                            {
                                "success": payload[0],
                                "results": payload[1],
                                "message": payload[2],
                                "error_code": payload[3],
                            },
                            timeout=EFPService._cache_ttl_for_error_code(payload[3]),
                        )
                    return payload
                payload = (False, [], "Деталь не найдена на сайте EFP Parts", "not_found")
                if use_cache:
                    cache.set(
                        EFPService._cache_key_for_search(normalized_oem),
                        {
                            "success": payload[0],
                            "results": payload[1],
                            "message": payload[2],
                            "error_code": payload[3],
                        },
                        timeout=EFPService._cache_ttl_for_error_code(payload[3]),
                    )
                return payload
            except Exception as e:
                logger.error(f"EFP Parts parsing error for OEM {oem_code}: {e}")
                payload = (False, [], f"Ошибка обработки данных: {str(e)}", "parse_error")
                if use_cache:
                    cache.set(
                        EFPService._cache_key_for_search(normalized_oem),
                        {
                            "success": payload[0],
                            "results": payload[1],
                            "message": payload[2],
                            "error_code": payload[3],
                        },
                        timeout=EFPService._cache_ttl_for_error_code(payload[3]),
                    )
                return payload

        logger.error(f"EFP Parts network unavailable for OEM {oem_code}: {network_errors}")
        payload = (
            False,
            [],
            "EFP Parts недоступен по сети (таймаут/соединение). Попробуйте позже или откройте поиск вручную.",
            "network_error",
        )
        if use_cache:
            cache.set(
                EFPService._cache_key_for_search(normalized_oem),
                {
                    "success": payload[0],
                    "results": payload[1],
                    "message": payload[2],
                    "error_code": payload[3],
                },
                timeout=EFPService._cache_ttl_for_error_code(payload[3]),
            )
        return payload
    
    @staticmethod
    def _parse_product_card(card, oem_code: str) -> dict | None:
        """Парсит карточку товара из HTML."""
        try:
            result = {
                "oem": oem_code,
                "name": "",
                "brand": "",
                "photo_url": "",
                "price": "",
                "availability": "",
                "detail_url": "",
            }
            
            # Название
            name_elem = card.find(['h2', 'h3', 'h4', 'a', 'span'], class_=re.compile(r'title|name|product', re.I))
            if not name_elem:
                name_elem = card.find('a')
            if name_elem:
                result["name"] = name_elem.get_text(strip=True)
                # Ссылка
                if name_elem.name == 'a' and name_elem.get('href'):
                    href = name_elem.get('href')
                    result["detail_url"] = urljoin(EFPService.BASE_URL, href)
            
            # Фото
            img = card.find('img')
            if img:
                img_src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
                if img_src:
                    result["photo_url"] = urljoin(EFPService.BASE_URL, img_src)
            
            # Бренд
            brand_elem = card.find(['span', 'div'], class_=re.compile(r'brand|manufacturer|producer', re.I))
            if brand_elem:
                result["brand"] = brand_elem.get_text(strip=True)
            
            # Цена
            price_elem = card.find(['span', 'div'], class_=re.compile(r'price|cost', re.I))
            if price_elem:
                result["price"] = price_elem.get_text(strip=True)
            
            # Наличие
            availability_elem = card.find(['span', 'div'], class_=re.compile(r'availability|stock|in-stock', re.I))
            if availability_elem:
                result["availability"] = availability_elem.get_text(strip=True)
            
            # Если есть хотя бы название, возвращаем результат
            if result["name"]:
                return result
                
        except Exception as e:
            logger.warning(f"Error in _parse_product_card: {e}")
        
        return None
    
    @staticmethod
    def _parse_main_page(soup, oem_code: str) -> dict | None:
        """Парсит основную страницу, если не найдены карточки."""
        try:
            result = {
                "oem": oem_code,
                "name": "",
                "brand": "",
                "photo_url": "",
                "price": "",
                "availability": "",
                "detail_url": "",
            }
            
            # Ищем заголовок страницы
            title = soup.find('title')
            if title:
                result["name"] = title.get_text(strip=True)
            
            # Ищем h1
            h1 = soup.find('h1')
            if h1 and not result["name"]:
                result["name"] = h1.get_text(strip=True)
            
            # Ищем фото
            img = soup.find('img', class_=re.compile(r'product|main|photo', re.I))
            if not img:
                img = soup.find('img')
            if img:
                img_src = img.get('src') or img.get('data-src')
                if img_src:
                    result["photo_url"] = urljoin(EFPService.BASE_URL, img_src)
            
            # Ищем цену
            price_elem = soup.find(['span', 'div'], class_=re.compile(r'price|cost', re.I))
            if price_elem:
                result["price"] = price_elem.get_text(strip=True)
            
            if result["name"]:
                return result
                
        except Exception as e:
            logger.warning(f"Error in _parse_main_page: {e}")
        
        return None
    
    @staticmethod
    def get_part_detail(url: str) -> tuple[bool, dict, str, str]:
        """
        Получает подробные характеристики детали по URL.
        
        Args:
            url: URL страницы детали
            
        Returns:
            (success: bool, detail: dict, message: str)
        """
        if not url:
            return False, {}, "URL не указан", "validation_error"

        network_errors: list[str] = []

        for candidate_url in EFPService._build_detail_urls(url):
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
                "Referer": f"http://{EFPService.BASE_HOST}/",
            }

            try:
                response = requests.get(candidate_url, headers=headers, timeout=EFPService.TIMEOUT, allow_redirects=True)
                response.raise_for_status()
            except requests.exceptions.Timeout:
                network_errors.append(f"timeout:{candidate_url}")
                continue
            except requests.exceptions.RequestException as e:
                network_errors.append(f"request_error:{candidate_url}:{e}")
                continue

            soup = BeautifulSoup(response.text, "html.parser")
            denied, denied_message = EFPService._check_access_denied(soup, response.url)
            if denied:
                return False, {}, denied_message, "access_denied"

            try:
                detail = {
                    "name": "",
                    "brand": "",
                    "photo_url": "",
                    "price": "",
                    "availability": "",
                    "characteristics": {},
                    "description": "",
                }

                # Название
                h1 = soup.find("h1")
                if h1:
                    detail["name"] = h1.get_text(strip=True)

                # Фото
                img = soup.find("img", class_=re.compile(r"product|main|photo", re.I))
                if img:
                    img_src = img.get("src") or img.get("data-src")
                    if img_src:
                        detail["photo_url"] = urljoin(response.url, img_src)

                # Характеристики (таблица или список)
                specs_table = soup.find("table", class_=re.compile(r"spec|characteristic", re.I))
                if specs_table:
                    rows = specs_table.find_all("tr")
                    for row in rows:
                        cells = row.find_all(["td", "th"])
                        if len(cells) >= 2:
                            key = cells[0].get_text(strip=True)
                            value = cells[1].get_text(strip=True)
                            detail["characteristics"][key] = value

                # Описание
                desc = soup.find("div", class_=re.compile(r"description|about", re.I))
                if desc:
                    detail["description"] = desc.get_text(strip=True)

                return True, detail, "Данные получены", "ok"
            except Exception as e:
                logger.error(f"Error parsing part detail from {candidate_url}: {e}")
                return False, {}, f"Ошибка обработки данных: {str(e)}", "parse_error"

        logger.error(f"Error getting part detail from {url}: {network_errors}")
        return (
            False,
            {},
            "EFP Parts недоступен по сети (таймаут/соединение). Попробуйте позже или откройте карточку вручную.",
            "network_error",
        )
