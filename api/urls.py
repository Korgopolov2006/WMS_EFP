from django.urls import include, path

from . import views

urlpatterns = [
    path("v1/", include("api.v1.urls")),
    path("v1/products/search/", views.product_search, name="product_search"),
]

