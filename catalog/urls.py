from django.urls import path

from . import barcode_views, views, views_api

urlpatterns = [
    path("admin/", views.admin_home, name="catalog_admin_home"),
    path("admin/brands/", views.brand_list, name="catalog_brand_list"),
    path("admin/brands/new/", views.brand_create, name="catalog_brand_create"),
    path("admin/brands/<int:pk>/edit/", views.brand_update, name="catalog_brand_update"),
    path("admin/categories/", views.category_list, name="catalog_category_list"),
    path("admin/categories/new/", views.category_create, name="catalog_category_create"),
    path("admin/categories/<int:pk>/edit/", views.category_update, name="catalog_category_update"),
    path("admin/vehicles/makes/", views.vehicle_make_list, name="catalog_vehicle_make_list"),
    path("admin/vehicles/makes/new/", views.vehicle_make_create, name="catalog_vehicle_make_create"),
    path("admin/vehicles/makes/<int:pk>/edit/", views.vehicle_make_update, name="catalog_vehicle_make_update"),
    path("admin/vehicles/models/", views.vehicle_model_list, name="catalog_vehicle_model_list"),
    path("admin/vehicles/models/new/", views.vehicle_model_create, name="catalog_vehicle_model_create"),
    path("admin/vehicles/models/<int:pk>/edit/", views.vehicle_model_update, name="catalog_vehicle_model_update"),
    path("admin/zones/types/", views.zone_type_list, name="catalog_zone_type_list"),
    path("admin/zones/types/new/", views.zone_type_create, name="catalog_zone_type_create"),
    path("admin/zones/types/<int:pk>/edit/", views.zone_type_update, name="catalog_zone_type_update"),
    path("admin/storage/map/", views.storage_map, name="catalog_storage_map"),
    path("api/warehouses/", views_api.warehouses_list, name="catalog_warehouses_list"),
    path("api/warehouses/<int:warehouse_id>/data/", views_api.warehouse_data_json, name="catalog_warehouse_data_json"),
    path("api/warehouses/<int:warehouse_id>/objects/", views_api.warehouse_object_create, name="catalog_warehouse_object_create"),
    path("api/warehouses/<int:warehouse_id>/objects/<int:pk>/", views_api.warehouse_object_delete, name="catalog_warehouse_object_delete"),
    path("admin/products/", views.product_list, name="catalog_product_list"),
    path("admin/products/audit/", views.product_audit_list, name="catalog_product_audit_list"),
    path("admin/products/new/", views.product_create, name="catalog_product_create"),
    path("admin/products/<int:pk>/edit/", views.product_update, name="catalog_product_update"),
    path("admin/products/<int:pk>/xref/", views.product_xref, name="catalog_product_xref"),
    path("admin/products/<int:pk>/xref/<int:xref_id>/delete/", views.product_xref_delete, name="catalog_product_xref_delete"),

    # ── Штрихкоды / QR / этикетки / сканер ─────────────────────
    path("codes/barcode/<str:sku>.png", barcode_views.barcode_image, name="catalog_barcode_image"),
    path("codes/qr/<str:sku>.png", barcode_views.qr_image, name="catalog_qr_image"),
    path("codes/label/<str:sku>/", barcode_views.label_view, name="catalog_label"),
    path("codes/labels/", barcode_views.labels_bulk_view, name="catalog_labels_bulk"),
    path("codes/scan/", barcode_views.scanner_view, name="catalog_scanner"),
    path("codes/lookup/", barcode_views.lookup_by_code, name="catalog_code_lookup"),
]
