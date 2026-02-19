from django.urls import path

from . import views

urlpatterns = [
    path("", views.receiving_list, name="receiving_list"),
    path("new/", views.receiving_create, name="receiving_create"),
    path("<int:pk>/", views.receiving_detail, name="receiving_detail"),
    path("<int:pk>/add-line/", views.receiving_add_line, name="receiving_add_line"),
    path("<int:pk>/pdf/", views.receiving_pdf, name="receiving_pdf"),
]
