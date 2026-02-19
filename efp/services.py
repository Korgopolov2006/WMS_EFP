"""
Сервис для работы с сайтом EFP Parts (efp-parts.ru).
Поиск деталей по OEM коду.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class EFPService:
    """Сервис для работы с EFP Parts API."""
    
    BASE_URL = "https://efp-parts.ru"
    SEARCH_URL = "https://efp-parts.ru/search"
    TIMEOUT = 10  # секунд
    
    @staticmethod
    def search_part(oem_code: str) -> tuple[bool, list[dict], str]:
        """
        Поиск деталей по OEM коду на сайте EFP Parts.
        
        Args:
            oem_code: OEM код детали (число после pcode=)
            
        Returns:
            (success: bool, results: list[dict], message: str)
            
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
        if not oem_code or not oem_code.strip():
            return False, [], "OEM код не указан"
        
        oem_code = oem_code.strip()
        
        try:
            # Формируем URL для поиска
            search_url = f"{EFPService.SEARCH_URL}?pcode={oem_code}"
            
            logger.info(f"Searching EFP Parts for OEM: {oem_code}")
            
            # Делаем запрос
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response = requests.get(search_url, headers=headers, timeout=EFPService.TIMEOUT)
            response.raise_for_status()
            
            # Парсим HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            
            results = []
            
            # Ищем карточки товаров (адаптируем под структуру сайта EFP)
            # Обычно товары находятся в контейнерах с классом product, item, card и т.д.
            product_cards = soup.find_all(['div', 'article'], class_=re.compile(r'product|item|card|goods', re.I))
            
            if not product_cards:
                # Пробуем найти по другим селекторам
                product_cards = soup.find_all('div', class_=re.compile(r'catalog|search', re.I))
            
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
                return True, results, f"Найдено {len(results)} деталей"
            else:
                return False, [], "Деталь не найдена на сайте EFP Parts"
                
        except requests.exceptions.Timeout:
            logger.error(f"EFP Parts timeout for OEM: {oem_code}")
            return False, [], "Сайт недоступен, попробуйте позже"
        except requests.exceptions.RequestException as e:
            logger.error(f"EFP Parts request error for OEM {oem_code}: {e}")
            return False, [], f"Ошибка подключения к сайту: {str(e)}"
        except Exception as e:
            logger.error(f"EFP Parts parsing error for OEM {oem_code}: {e}")
            return False, [], f"Ошибка обработки данных: {str(e)}"
    
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
    def get_part_detail(url: str) -> tuple[bool, dict, str]:
        """
        Получает подробные характеристики детали по URL.
        
        Args:
            url: URL страницы детали
            
        Returns:
            (success: bool, detail: dict, message: str)
        """
        if not url:
            return False, {}, "URL не указан"
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response = requests.get(url, headers=headers, timeout=EFPService.TIMEOUT)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
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
            h1 = soup.find('h1')
            if h1:
                detail["name"] = h1.get_text(strip=True)
            
            # Фото
            img = soup.find('img', class_=re.compile(r'product|main|photo', re.I))
            if img:
                img_src = img.get('src') or img.get('data-src')
                if img_src:
                    detail["photo_url"] = urljoin(EFPService.BASE_URL, img_src)
            
            # Характеристики (таблица или список)
            specs_table = soup.find('table', class_=re.compile(r'spec|characteristic', re.I))
            if specs_table:
                rows = specs_table.find_all('tr')
                for row in rows:
                    cells = row.find_all(['td', 'th'])
                    if len(cells) >= 2:
                        key = cells[0].get_text(strip=True)
                        value = cells[1].get_text(strip=True)
                        detail["characteristics"][key] = value
            
            # Описание
            desc = soup.find('div', class_=re.compile(r'description|about', re.I))
            if desc:
                detail["description"] = desc.get_text(strip=True)
            
            return True, detail, "Данные получены"
            
        except Exception as e:
            logger.error(f"Error getting part detail from {url}: {e}")
            return False, {}, f"Ошибка получения данных: {str(e)}"
