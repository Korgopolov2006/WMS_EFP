"""
Настройки Django Admin для всего проекта.
"""

from django.contrib import admin
from django.contrib.admin import AdminSite


class WMSAdminSite(AdminSite):
    """Кастомный админ-сайт для WMS."""

    site_header = "WMS - Система управления складом"
    site_title = "WMS Admin"
    index_title = "Администрирование"


# Используем стандартный админ-сайт, но можно переопределить
admin_site = admin.site
