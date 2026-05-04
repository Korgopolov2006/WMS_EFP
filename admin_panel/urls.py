"""URL-маршруты административной панели WMS."""
from django.urls import path

from . import views

app_name = "admin_panel"

urlpatterns = [
    # ── Дашборд ────────────────────────────────────────────
    path("", views.dashboard, name="dashboard"),

    # ── Пользователи ───────────────────────────────────────
    path("users/", views.user_list, name="user_list"),
    path("users/create/", views.user_create, name="user_create"),
    path("users/<int:pk>/", views.user_detail, name="user_detail"),
    path("users/<int:pk>/edit/", views.user_edit, name="user_edit"),
    path("users/<int:pk>/delete/", views.user_delete, name="user_delete"),
    path("users/<int:pk>/toggle-active/", views.user_toggle_active, name="user_toggle_active"),
    path("users/bulk/", views.user_bulk_action, name="user_bulk"),
    path("users/<int:pk>/reset-password/", views.user_reset_password, name="user_reset_password"),

    # ── Журнал аудита ──────────────────────────────────────
    path("audit/", views.audit_log_list, name="audit_list"),

    # ── Резервные копии ────────────────────────────────────
    path("backups/", views.backup_list, name="backup_list"),
    path("backups/create/", views.backup_create, name="backup_create"),
    path("backups/upload/", views.backup_upload, name="backup_upload"),
    path("backups/<str:filename>/download/", views.backup_download, name="backup_download"),
    path("backups/<str:filename>/delete/", views.backup_delete_view, name="backup_delete"),
    path("backups/<str:filename>/restore/", views.backup_restore, name="backup_restore"),

    # ── Настройки ──────────────────────────────────────────
    path("settings/", views.system_settings, name="settings"),

    # ══ WMS-сущности ═══════════════════════════════════════

    # ── Склады ─────────────────────────────────────────────
    path("warehouses/", views.wms_warehouse_list, name="wms_warehouse_list"),
    path("warehouses/create/", views.wms_warehouse_create, name="wms_warehouse_create"),
    path("warehouses/<int:pk>/edit/", views.wms_warehouse_edit, name="wms_warehouse_edit"),
    path("warehouses/<int:pk>/delete/", views.wms_warehouse_delete, name="wms_warehouse_delete"),

    # ── Поставщики ─────────────────────────────────────────
    path("suppliers/", views.wms_supplier_list, name="wms_supplier_list"),
    path("suppliers/create/", views.wms_supplier_create, name="wms_supplier_create"),
    path("suppliers/<int:pk>/edit/", views.wms_supplier_edit, name="wms_supplier_edit"),
    path("suppliers/<int:pk>/toggle/", views.wms_supplier_toggle_active, name="wms_supplier_toggle"),
    path("suppliers/<int:pk>/delete/", views.wms_supplier_delete, name="wms_supplier_delete"),

    # ── Товары ─────────────────────────────────────────────
    path("products/", views.wms_product_list, name="wms_product_list"),
    path("products/bulk/", views.wms_product_bulk_action, name="wms_product_bulk"),

    # ── Заказы ─────────────────────────────────────────────
    path("orders/", views.wms_order_list, name="wms_order_list"),

    # ── Остатки ────────────────────────────────────────────
    path("stock/", views.wms_stock_list, name="wms_stock_list"),

    # ── Приёмки ────────────────────────────────────────────
    path("receivings/", views.wms_receiving_list, name="wms_receiving_list"),

    # ── Задачи ─────────────────────────────────────────────
    path("tasks/", views.wms_task_list, name="wms_task_list"),
]
