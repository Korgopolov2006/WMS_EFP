"""
Views для интеграции с EFP Parts.
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods

from accounts.constants import Roles
from accounts.permissions import role_required

from .services import EFPService


@role_required(Roles.STOREKEEPER, Roles.ADMIN)
@login_required
@require_http_methods(["GET"])
def search_part(request: HttpRequest) -> JsonResponse:
    """
    API для поиска детали на EFP Parts по OEM коду.
    
    Параметры:
    - oem: OEM код детали
    """
    oem_code = request.GET.get("oem", "").strip()
    
    if not oem_code:
        return JsonResponse({
            "success": False,
            "error": "OEM код не указан"
        }, status=400)
    
    success, results, message = EFPService.search_part(oem_code)
    
    if success:
        return JsonResponse({
            "success": True,
            "results": results,
            "message": message
        })
    else:
        return JsonResponse({
            "success": False,
            "error": message,
            "results": []
        }, status=404)


@role_required(Roles.STOREKEEPER, Roles.ADMIN)
@login_required
@require_http_methods(["GET"])
def get_part_detail(request: HttpRequest) -> JsonResponse:
    """
    API для получения подробных характеристик детали.
    
    Параметры:
    - url: URL страницы детали на EFP Parts
    """
    url = request.GET.get("url", "").strip()
    
    if not url:
        return JsonResponse({
            "success": False,
            "error": "URL не указан"
        }, status=400)
    
    success, detail, message = EFPService.get_part_detail(url)
    
    if success:
        return JsonResponse({
            "success": True,
            "detail": detail,
            "message": message
        })
    else:
        return JsonResponse({
            "success": False,
            "error": message
        }, status=404)
