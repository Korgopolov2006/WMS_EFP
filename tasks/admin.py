from django.contrib import admin
from django.utils.html import format_html

from .models import Task, TaskComment, TaskStatus, TaskType, TaskPriority


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "title",
        "task_type",
        "status",
        "priority",
        "assigned_to",
        "created_by",
        "due_date",
        "created_at",
    ]
    list_filter = ["task_type", "status", "priority", "created_at", "due_date"]
    search_fields = ["title", "description", "created_by__username", "assigned_to__username"]
    readonly_fields = ["created_at", "updated_at", "status_display"]
    autocomplete_fields = ["assigned_to", "created_by", "receiving", "inventory", "order", "picking_task"]
    date_hierarchy = "created_at"
    fieldsets = (
        ("Основная информация", {"fields": ("task_type", "title", "description", "priority")}),
        ("Статус", {"fields": ("status", "status_display", "due_date", "started_at", "completed_at")}),
        ("Связи", {"fields": ("receiving", "inventory", "order", "picking_task")}),
        ("Исполнители", {"fields": ("assigned_to", "created_by")}),
        ("Метаданные", {"fields": ("metadata",)}),
        ("Системные", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def status_display(self, obj):
        colors = {
            TaskStatus.PENDING: "gray",
            TaskStatus.IN_PROGRESS: "blue",
            TaskStatus.COMPLETED: "green",
            TaskStatus.CANCELLED: "red",
            TaskStatus.ON_HOLD: "orange",
        }
        color = colors.get(obj.status, "black")
        return format_html('<span style="color: {};">{}</span>', color, obj.get_status_display())
    status_display.short_description = "Статус (визуально)"


@admin.register(TaskComment)
class TaskCommentAdmin(admin.ModelAdmin):
    list_display = ["task", "author", "created_at"]
    list_filter = ["created_at"]
    search_fields = ["text", "task__title", "author__username"]
    readonly_fields = ["created_at", "updated_at"]
    autocomplete_fields = ["task", "author"]
