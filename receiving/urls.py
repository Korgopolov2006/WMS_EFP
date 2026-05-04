from django.urls import path

from . import views

urlpatterns = [
    path("", views.receiving_list, name="receiving_list"),
    path("suppliers/", views.supplier_list, name="supplier_list"),
    path("suppliers/new/", views.supplier_create, name="supplier_create"),
    path("new/", views.receiving_create, name="receiving_create"),
    path("next-supplier-doc/", views.receiving_next_supplier_doc, name="receiving_next_supplier_doc"),
    path("<int:pk>/", views.receiving_detail, name="receiving_detail"),
    path("<int:pk>/new-product/", views.receiving_create_product, name="receiving_create_product"),
    path("<int:pk>/product-prefill/", views.receiving_product_prefill, name="receiving_product_prefill"),
    path("<int:pk>/add-line/", views.receiving_add_line, name="receiving_add_line"),
    path("<int:pk>/lines/<int:line_id>/qty/", views.receiving_update_line_qty, name="receiving_update_line_qty"),
    path("<int:pk>/suggest-location/", views.receiving_suggest_location, name="receiving_suggest_location"),
    path("<int:pk>/pdf/", views.receiving_pdf, name="receiving_pdf"),
]
