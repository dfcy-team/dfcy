from django.urls import path
from .views import SupplierPurchases, SupplierShipments
from .api import SupplierPurchaseFile, SupplierPurchaseLabels
from . import shipment_api as sa
from .internal_product_images import SupplierShipmentProductImage

urlpatterns = [
    path("me/", sa.SupplierIdentity.as_view(), name="sc2-supplier-me"),
    path("options/", sa.SupplierOptions.as_view(), name="sc2-supplier-options"),
    path("shipment-options/", sa.SupplierOptions.as_view(), name="sc2-supplier-shipment-options"),
    path("shipment-options/skus/<int:sku_id>/image/", sa.SupplierOptionProductImage.as_view(), name="sc2-supplier-shipment-option-image"),
    path("purchase-orders/", sa.SupplierOrderList.as_view(), name="sc2-supplier-purchases"),
    path("purchase-orders/<int:pk>/", sa.SupplierOrderDetail.as_view(), name="sc2-supplier-purchase-detail"),
    path("purchase-orders/<int:pk>/excel/", SupplierPurchaseFile.as_view(), name="sc2-supplier-excel"),
    path("purchase-orders/<int:pk>/labels/", SupplierPurchaseLabels.as_view(), name="sc2-supplier-labels"),
    path("purchase-orders/<int:pk>/skus/<int:sku_id>/labels/", SupplierPurchaseLabels.as_view(), name="sc2-supplier-sku-labels"),
    path("purchase-orders/<int:pk>/skus/<int:sku_id>/image/", sa.SupplierProductImage.as_view(), name="sc2-supplier-product-image"),
    path("shipments/", sa.SupplierShipmentList.as_view(), name="sc2-supplier-shipments"),
    path("shipments/<int:pk>/", sa.SupplierShipmentDetail.as_view(), name="sc2-supplier-shipment-detail"),
    path("shipments/<int:pk>/skus/<int:sku_id>/image/", SupplierShipmentProductImage.as_view(), name="sc2-supplier-shipment-image"),
    path("shipments/<int:pk>/submit/", sa.SupplierShipmentAction.as_view(), name="sc2-supplier-shipment-submit"),
    path("shipments/<int:pk>/cancel/", sa.SupplierShipmentCancel.as_view(), name="sc2-supplier-shipment-cancel"),
    path("shipments/<int:pk>/attachments/", sa.SupplierShipmentUpload.as_view(), name="sc2-supplier-shipment-upload"),
    path("shipments/<int:pk>/attachments/<int:attachment_id>/remove/", sa.SupplierShipmentRemove.as_view(), name="sc2-supplier-shipment-remove"),
    path("shipments/<int:pk>/attachments/<int:attachment_id>/download/", sa.SupplierShipmentDownload.as_view(), name="sc2-supplier-shipment-download"),
]
