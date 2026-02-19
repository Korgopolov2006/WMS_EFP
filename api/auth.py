from __future__ import annotations

from datetime import datetime

from django.http import HttpRequest
from django.utils.timezone import now

from accounts.constants import Roles

from .models import ApiToken


class ApiAuthError(Exception):
    pass


def get_bearer_token(request: HttpRequest) -> str | None:
    header = request.headers.get("Authorization") or request.META.get("HTTP_AUTHORIZATION")
    if not header:
        return None
    parts = header.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


def authenticate_integration(request: HttpRequest):
    token = get_bearer_token(request)
    if not token:
        raise ApiAuthError("Missing Authorization: Bearer <token>")

    try:
        api_token = ApiToken.objects.select_related("user").get(token=token, is_active=True)
    except ApiToken.DoesNotExist as e:
        raise ApiAuthError("Invalid token") from e

    user = api_token.user
    if not getattr(user, "is_active", False):
        raise ApiAuthError("User inactive")
    if getattr(user, "role", None) != Roles.INTEGRATION and not getattr(user, "is_superuser", False):
        raise ApiAuthError("User role is not allowed for API")

    ApiToken.objects.filter(pk=api_token.pk).update(last_used_at=now())
    return user, api_token

