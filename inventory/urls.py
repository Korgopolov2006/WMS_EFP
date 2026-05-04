from django.urls import path

from . import views

urlpatterns = [
    path("stock/", views.stock_list, name="stock_list"),
    path("stock/<int:pk>/", views.stock_detail, name="stock_detail"),
    path("inventory/", views.inventory_list, name="inventory_list"),
    path("inventory/new/", views.inventory_create, name="inventory_create"),
    path("inventory/<int:pk>/product-hint/", views.inventory_product_hint, name="inventory_product_hint"),
    path("inventory/<int:pk>/", views.inventory_detail, name="inventory_detail"),
    path("movements/", views.movement_list, name="movement_list"),
]
