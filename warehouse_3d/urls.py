from django.urls import path

from . import views

app_name = "warehouse_3d"

urlpatterns = [
    # ── Pages ──
    path("warehouse/", views.warehouse_3d_index, name="index"),
    path("warehouse/<int:warehouse_id>/", views.warehouse_3d_view, name="view"),

    # ── CRUD layout/object ──
    path("warehouse/<int:warehouse_id>/layout/save/", views.save_layout, name="save_layout"),
    path("warehouse/<int:warehouse_id>/object/save/", views.save_storage_object, name="save_object"),
    path(
        "warehouse/<int:warehouse_id>/object/<int:object_id>/delete/",
        views.delete_storage_object, name="delete_object",
    ),

    # ── KPI / Поиск / Heatmap движений / Импорт-Экспорт ──
    path("warehouse/<int:warehouse_id>/api/kpi/", views.kpi_data, name="kpi_data"),
    path("warehouse/<int:warehouse_id>/api/locate/", views.locate_sku, name="locate_sku"),
    path("warehouse/<int:warehouse_id>/api/movement-heatmap/", views.movement_heatmap, name="movement_heatmap"),
    path("warehouse/<int:warehouse_id>/api/layout/export/", views.export_layout, name="export_layout"),
    path("warehouse/<int:warehouse_id>/api/layout/import/", views.import_layout, name="import_layout"),

    # ── #1 авто-генерация стеллажей ──
    path("warehouse/<int:warehouse_id>/api/objects/bulk-generate/",
         views.bulk_generate_objects, name="bulk_generate_objects"),

    # ── #14 audit + rollback ──
    path("warehouse/<int:warehouse_id>/api/audit/", views.layout_audit, name="layout_audit"),
    path("warehouse/<int:warehouse_id>/api/audit/<int:audit_id>/rollback/",
         views.layout_audit_rollback, name="layout_audit_rollback"),

    # ── #13 QR-этикетка PDF ──
    path("warehouse/<int:warehouse_id>/api/object/<int:object_id>/qr/",
         views.object_qr_pdf, name="object_qr"),

    # ── #2 маршрут комплектования ──
    path("warehouse/<int:warehouse_id>/api/pickpath/", views.pick_path, name="pick_path"),

    # ── #8 inline-edit товаров ──
    path("warehouse/<int:warehouse_id>/api/object/<int:object_id>/stocks/",
         views.object_stocks, name="object_stocks"),
    path("warehouse/<int:warehouse_id>/api/object/<int:object_id>/stock-action/",
         views.stock_action, name="stock_action"),

    # ── #9 long-polling ──
    path("warehouse/<int:warehouse_id>/api/recent-movements/",
         views.recent_movements, name="recent_movements"),

    # ── Интеграция с модулем приёмки ──
    path("api/objects-for-receiving/<int:warehouse_id>/",
         views.objects_for_receiving, name="objects_for_receiving"),
]
