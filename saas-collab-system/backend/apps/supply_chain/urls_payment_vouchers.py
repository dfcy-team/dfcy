from django.urls import path

from .payment_vouchers import (PaymentVoucherDownload, PaymentVouchers,
    PaymentRecordVouchers, PaymentRecordVoucherDownload)

urlpatterns = [
    path("costs/<str:kind>/<int:pk>/settlements/<int:revision_id>/vouchers/",
         PaymentVouchers.as_view(), name="sc2-settlement-vouchers"),
    path("costs/<str:kind>/<int:pk>/settlements/<int:revision_id>/vouchers/<int:voucher_id>/download/",
         PaymentVoucherDownload.as_view(), name="sc2-settlement-voucher-download"),
    path("costs/<str:kind>/<int:pk>/payments/<int:payment_id>/vouchers/",
         PaymentRecordVouchers.as_view(), name="sc2-payment-vouchers"),
    path("costs/<str:kind>/<int:pk>/payments/<int:payment_id>/vouchers/<int:voucher_id>/download/",
         PaymentRecordVoucherDownload.as_view(), name="sc2-payment-voucher-download"),
]
