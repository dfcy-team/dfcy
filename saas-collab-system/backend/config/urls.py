"""Root URL configuration for the backend project."""
from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/internal/", include("apps.accounts.urls_internal")),
    path("api/internal/integrations/", include("apps.integrations.urls_internal")),
    path("api/internal/analytics/", include("apps.reports.urls_internal")),
    path("api/internal/alerts/", include("apps.alerts.urls")),
    path("api/internal/replenishment/", include("apps.replenishment.urls")),
    path("api/internal/lifecycle/", include("apps.products.urls_lifecycle")),
    path("api/internal/config/", include("apps.configcenter.urls")),
    path("api/internal/master-data/", include("apps.masterdata.urls")),
    path("api/internal/rpa/", include("apps.rpa.urls_internal")),
    path("api/internal/products/", include("apps.products.urls")),
    path("api/internal/purchasing/", include("apps.purchasing.urls")),
    path("api/internal/suppliers/", include("apps.suppliers.urls_internal")),
    path("api/external/", include("apps.accounts.urls_external")),
    path("api/external/supplier/", include("apps.suppliers.urls_external")),
    path("api/rpa/", include("apps.rpa.urls")),
    path("api/platform/", include("apps.integrations.urls_platform")),
    path("api/wechat/", include("apps.integrations.urls_wechat")),
    path("api/feishu/", include("apps.integrations.urls_feishu")),
    path("api/finance/", include("apps.finance.urls")),
    path("api/report/", include("apps.reports.urls")),
]
