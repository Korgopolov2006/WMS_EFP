from __future__ import annotations

from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse

from .openapi import build_openapi_spec


def openapi_json(request):
    from .urls import urlpatterns

    spec = build_openapi_spec(urlpatterns, request)
    return JsonResponse(spec, json_dumps_params={"ensure_ascii": False, "indent": 2})


def swagger_ui(request):
    return render(
        request,
        "api/v1/swagger.html",
        {
            "title": "WMS API Docs (Swagger)",
            "spec_url": reverse("api_v1_openapi"),
        },
    )


def redoc_ui(request):
    return render(
        request,
        "api/v1/redoc.html",
        {
            "title": "WMS API Docs (ReDoc)",
            "spec_url": reverse("api_v1_openapi"),
        },
    )
