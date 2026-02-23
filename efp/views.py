"""
Views для интеграции с EFP Parts.
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods

from accounts.constants import Roles
from accounts.permissions import role_required

from .queue import enqueue_efp_search, get_efp_search_job
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
    async_mode = (request.GET.get("async_mode") or "").strip().lower() in {"1", "true", "yes", "on"}
    task_id = (request.GET.get("task_id") or "").strip()
    
    if not oem_code:
        return JsonResponse({
            "success": False,
            "error": "OEM код не указан",
            "error_code": "validation_error",
        }, status=400)
    
    manual_url = EFPService.manual_search_url(oem_code)

    if async_mode:
        if task_id:
            job = get_efp_search_job(task_id)
            if not job:
                return JsonResponse(
                    {
                        "success": False,
                        "error": "Фоновая задача EFP не найдена или устарела",
                        "error_code": "task_not_found",
                        "manual_url": manual_url,
                    },
                    status=404,
                )

            status = str(job.get("status") or "")
            if status in {"queued", "running"}:
                return JsonResponse(
                    {
                        "success": False,
                        "queued": True,
                        "status": status,
                        "task_id": task_id,
                        "backend": job.get("backend") or "",
                        "queue_warning": job.get("queue_warning") or "",
                        "manual_url": manual_url,
                    },
                    status=202,
                )

            result = job.get("result") if isinstance(job.get("result"), dict) else {}
            success = bool(result.get("success"))
            if success:
                return JsonResponse(
                    {
                        "success": True,
                        "results": result.get("results") or [],
                        "message": result.get("message") or "Данные получены",
                        "manual_url": result.get("manual_url") or manual_url,
                        "queue_warning": job.get("queue_warning") or "",
                    }
                )

            error_code = str(result.get("error_code") or "queue_runtime_error")
            status_map = {
                "validation_error": 400,
                "not_found": 404,
                "access_denied": 503,
                "network_error": 503,
                "parse_error": 502,
                "queue_runtime_error": 502,
                "queue_timeout": 504,
            }
            return JsonResponse(
                {
                    "success": False,
                    "error": result.get("message") or "Ошибка фоновой проверки EFP",
                    "error_code": error_code,
                    "manual_url": result.get("manual_url") or manual_url,
                    "queue_warning": job.get("queue_warning") or "",
                    "results": [],
                },
                status=status_map.get(error_code, 502),
            )

        try:
            queued_task_id, backend, queue_warning = enqueue_efp_search(oem_code)
        except Exception as exc:
            return JsonResponse(
                {
                    "success": False,
                    "error": "Очередь Celery недоступна. Проверьте Redis и worker.",
                    "error_code": "queue_unavailable",
                    "details": str(exc),
                    "manual_url": manual_url,
                },
                status=503,
            )
        return JsonResponse(
            {
                "success": False,
                "queued": True,
                "status": "queued",
                "task_id": queued_task_id,
                "backend": backend,
                "queue_warning": queue_warning,
                "manual_url": manual_url,
            },
            status=202,
        )

    success, results, message, error_code = EFPService.search_part(oem_code, use_cache=True)

    if success:
        return JsonResponse({
            "success": True,
            "results": results,
            "message": message,
            "manual_url": manual_url,
        })

    status_map = {
        "validation_error": 400,
        "not_found": 404,
        "access_denied": 503,
        "network_error": 503,
        "parse_error": 502,
    }
    return JsonResponse(
        {
            "success": False,
            "error": message,
            "error_code": error_code,
            "manual_url": manual_url,
            "results": [],
        },
        status=status_map.get(error_code, 502),
    )


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
            "error": "URL не указан",
            "error_code": "validation_error",
        }, status=400)
    
    success, detail, message, error_code = EFPService.get_part_detail(url)
    
    if success:
        return JsonResponse({
            "success": True,
            "detail": detail,
            "message": message
        })

    status_map = {
        "validation_error": 400,
        "not_found": 404,
        "access_denied": 503,
        "network_error": 503,
        "parse_error": 502,
    }
    return JsonResponse(
        {
            "success": False,
            "error": message,
            "error_code": error_code,
        },
        status=status_map.get(error_code, 502),
    )
