from django.urls import path

from .payment_vouchers import PaymentVoucherDownload, PaymentVouchers

urlpatterns = [
    path("costs/<str:kind>/<int:pk>/settlements/<int:revision_id>/vouchers/",
         PaymentVouchers.as_view(), name="sc2-settlement-vouchers"),
    path("costs/<str:kind>/<int:pk>/settlements/<int:revision_id>/vouchers/<int:voucher_id>/download/",
         PaymentVoucherDownload.as_view(), name="sc2-settlement-voucher-download"),
]
