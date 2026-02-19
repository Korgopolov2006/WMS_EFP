from django.urls import path

from . import views

urlpatterns = [
    path("monitoring/", views.tasks_monitoring, name="tasks_monitoring"),
    path("api/monitoring/", views.tasks_monitoring_api, name="tasks_monitoring_api"),
    path("", views.task_list, name="task_list"),
    path("<int:task_id>/", views.task_detail, name="task_detail"),
]
