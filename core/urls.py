from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("manual/", views.user_manual, name="user_manual"),
    path("manual/download/", views.user_manual_download, name="user_manual_download"),
    path("integrations/", views.integrations, name="integrations"),
]
