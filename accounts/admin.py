from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html

from .constants import Roles
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ["username", "email", "first_name", "last_name", "role", "is_active", "is_staff", "date_joined"]
    list_filter = ["role", "is_active", "is_staff", "date_joined"]
    search_fields = ["username", "email", "first_name", "last_name"]
    readonly_fields = ["date_joined", "last_login", "role_display"]

    fieldsets = BaseUserAdmin.fieldsets + (
        ("Роль и доступ", {"fields": ("role", "role_display", "branches")}),
    )

    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("Роль и доступ", {"fields": ("role", "branches")}),
    )

    filter_horizontal = ["branches", "groups", "user_permissions"]

    def role_display(self, obj):
        colors = {
            Roles.ADMIN: "red",
            Roles.STOREKEEPER: "blue",
            Roles.SMALL_PARTS_PICKER: "green",
            Roles.LOADER: "orange",
            Roles.SALES_MANAGER: "purple",
            Roles.ANALYST: "teal",
            Roles.INTEGRATION: "gray",
        }
        color = colors.get(obj.role, "black")
        return format_html('<span style="color: {}; font-weight: bold;">{}</span>', color, obj.get_role_display())
    role_display.short_description = "Роль (визуально)"
