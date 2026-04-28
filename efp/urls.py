"""URL patterns для интеграции с EFP Parts."""

from django.urls import path

from . import views

app_name = "efp"

urlpatterns = [
    path("search/", views.search_part, name="search_part"),
    path("detail/", views.get_part_detail, name="get_part_detail"),
]
