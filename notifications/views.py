"""
Views уведомлений: список, дроп-даун последних, mark-as-read.
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Notification
from .services import mark_all_read, mark_read, unread_count


@login_required
def notification_list(request: HttpRequest) -> HttpResponse:
    """Полный список уведомлений с пагинацией и фильтром непрочитанных."""
    only_unread = request.GET.get("unread") == "1"
    qs = Notification.objects.filter(user=request.user)
    if only_unread:
        qs = qs.filter(is_read=False)

    paginator = Paginator(qs.order_by("-created_at"), 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "notifications/list.html", {
        "page_obj": page_obj,
        "items": page_obj.object_list,
        "only_unread": only_unread,
        "unread_count": unread_count(request.user),
    })


@login_required
def dropdown(request: HttpRequest) -> HttpResponse:
    """HTML-фрагмент: последние 5 уведомлений для bell-меню."""
    items = Notification.objects.filter(user=request.user).order_by("-created_at")[:5]
    return render(request, "notifications/_dropdown.html", {
        "items": items,
        "unread_count": unread_count(request.user),
    })


@login_required
def unread_count_api(request: HttpRequest) -> JsonResponse:
    """JSON-эндпоинт для polling-обновления счётчика."""
    return JsonResponse({"count": unread_count(request.user)})


@login_required
@require_POST
def mark_one_read(request: HttpRequest, pk: int) -> HttpResponse:
    notification = get_object_or_404(Notification, pk=pk, user=request.user)
    mark_read(notification)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "unread": unread_count(request.user)})
    return redirect(notification.link or "notifications:list")


@login_required
@require_POST
def mark_all(request: HttpRequest) -> HttpResponse:
    n = mark_all_read(request.user)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "updated": n, "unread": 0})
    return redirect("notifications:list")
