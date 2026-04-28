from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.notification_list, name="list"),
    path("dropdown/", views.dropdown, name="dropdown"),
    path("unread-count/", views.unread_count_api, name="unread_count"),
    path("<int:pk>/read/", views.mark_one_read, name="mark_read"),
    path("read-all/", views.mark_all, name="mark_all_read"),
]
