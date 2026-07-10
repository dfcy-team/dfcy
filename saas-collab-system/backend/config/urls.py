"""Root URL configuration for the backend project."""
from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/internal/", include("apps.accounts.urls_internal")),
    path("api/internal/integrations/", include("apps.integrations.urls_internal")),
    path("api/internal/products/", include("apps.products.urls")),
    path("api/internal/purchasing/", include("apps.purchasing.urls")),
    path("api/external/", include("apps.accounts.urls_external")),
    path("api/external/supplier/", include("apps.suppliers.urls_external")),
    path("api/rpa/", include("apps.rpa.urls")),
    path("api/platform/", include("apps.integrations.urls_platform")),
    path("api/wechat/", include("apps.integrations.urls_wechat")),
    path("api/feishu/", include("apps.integrations.urls_feishu")),
    path("api/finance/", include("apps.finance.urls")),
    path("api/report/", include("apps.reports.urls")),
]
