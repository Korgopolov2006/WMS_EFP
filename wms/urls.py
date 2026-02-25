from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
    path("accounts/", include("accounts.urls")),
    path("catalog/", include("catalog.urls")),
    path("receiving/", include("receiving.urls")),
    path("inventory/", include("inventory.urls")),
    path("picking/", include("picking.urls")),
    path("reports/", include("reports.urls")),
    path("tasks/", include("tasks.urls")),
    path("api/", include("api.urls")),
    path("3d/", include("warehouse_3d.urls")),
    path("efp/", include("efp.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler403 = "core.views.permission_denied_view"
