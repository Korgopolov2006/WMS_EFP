from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health, name="api_v1_health"),
    path("brands/", views.brands_list, name="api_v1_brands_list"),
    path("categories/", views.categories_list, name="api_v1_categories_list"),
    path("vehicles/makes/", views.vehicle_makes_list, name="api_v1_vehicle_makes_list"),
    path("vehicles/models/", views.vehicle_models_list, name="api_v1_vehicle_models_list"),
    path("products/", views.products_list, name="api_v1_products_list"),
    path("products/<int:pk>/", views.product_detail, name="api_v1_product_detail"),
    path("products/<int:pk>/xrefs/", views.product_xrefs_list, name="api_v1_product_xrefs_list"),
    path("receivings/", views.receivings_list, name="api_v1_receivings_list"),
    path("receivings/<int:pk>/", views.receiving_detail_api, name="api_v1_receiving_detail"),
    path("receivings/<int:pk>/lines/", views.receiving_lines_list_create, name="api_v1_receiving_lines"),
    path("receivings/<int:pk>/scan/", views.receiving_scan, name="api_v1_receiving_scan"),
    path("stock/", views.stock_list, name="api_v1_stock_list"),
    path("stock/<int:pk>/analogs/", views.stock_analogs, name="api_v1_stock_analogs"),
    path("inventories/", views.inventories_list, name="api_v1_inventories_list"),
    path("orders/", views.orders_list_create, name="api_v1_orders_list_create"),
    path("orders/<int:pk>/", views.order_detail_update, name="api_v1_order_detail_update"),
    path("orders/<int:pk>/lines/", views.order_lines_list_create, name="api_v1_order_lines_list_create"),
    path("picking-tasks/", views.picking_tasks_list, name="api_v1_picking_tasks_list"),
    path("reports/abc-xyz/", views.reports_abc_xyz, name="api_v1_reports_abc_xyz"),
    path("reports/dead-stock/", views.reports_dead_stock, name="api_v1_reports_dead_stock"),
    path("reports/analogs-vs-originals/", views.reports_analogs_vs_originals, name="api_v1_reports_analogs_vs_originals"),
    path("reports/picking-errors/", views.reports_picking_errors, name="api_v1_reports_picking_errors"),
]

