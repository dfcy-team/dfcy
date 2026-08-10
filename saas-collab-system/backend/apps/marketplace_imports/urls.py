from django.urls import path

from . import views


urlpatterns = [
    path("imports/", views.import_collection, name="marketplace-import-collection"),
    path("batches/", views.batch_collection, name="marketplace-import-batches"),
    path("batches/<int:pk>/retry/", views.retry_batch, name="marketplace-import-retry"),
    path("orders/", views.order_collection, name="marketplace-import-orders"),
    path("inventory/", views.inventory_collection, name="marketplace-import-inventory"),
]
