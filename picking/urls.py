from django.urls import path

from . import views

urlpatterns = [
    path("orders/", views.order_list, name="order_list"),
    path("orders/new/", views.order_create, name="order_create"),
    path("orders/<int:pk>/", views.order_detail, name="order_detail"),
    path("orders/<int:pk>/lines/<int:line_pk>/delete/", views.order_line_delete, name="order_line_delete"),
    path("tasks/", views.picking_task_list, name="picking_task_list"),
    path("tasks/<int:pk>/", views.picking_task_detail, name="picking_task_detail"),
    path("ajax/product-search/", views.product_search_ajax, name="picking_product_search_ajax"),
]
