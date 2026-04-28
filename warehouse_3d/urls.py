from django.urls import path

from . import views

app_name = "warehouse_3d"

urlpatterns = [
    path("warehouse/", views.warehouse_3d_index, name="index"),
    path("warehouse/<int:warehouse_id>/", views.warehouse_3d_view, name="view"),
    path("warehouse/<int:warehouse_id>/layout/save/", views.save_layout, name="save_layout"),
    path("warehouse/<int:warehouse_id>/object/save/", views.save_storage_object, name="save_object"),
    path(
        "warehouse/<int:warehouse_id>/object/<int:object_id>/delete/",
        views.delete_storage_object,
        name="delete_object",
    ),
]
