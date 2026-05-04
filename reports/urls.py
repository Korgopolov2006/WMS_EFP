from django.urls import path

from . import views

urlpatterns = [
    path("", views.reports_home, name="reports_home"),
    path("autogenerate/", views.reports_autogenerate, name="reports_autogenerate"),
    path("abc-xyz/", views.report_abc_xyz, name="report_abc_xyz"),
    path("dead-stock/", views.report_dead_stock, name="report_dead_stock"),
    path("analogs-vs-originals/", views.report_analogs_vs_originals, name="report_analogs_vs_originals"),
    path("picking-errors/", views.report_picking_errors, name="report_picking_errors"),
    path("demand-forecast/", views.report_demand_forecast, name="report_demand_forecast"),
    path("staff-efficiency/", views.report_staff_efficiency, name="report_staff_efficiency"),
    path("api/<str:report_type>/", views.report_data_json, name="report_data_json"),
]
