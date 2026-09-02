from django.urls import path

from . import api_views as views


urlpatterns = [
    path("", views.internal_shipment_collection, name="supply-shipments"),
    path("<int:pk>/", views.internal_shipment_detail, name="supply-shipment-detail"),
    path("<int:pk>/boxes/", views.internal_shipment_boxes, name="supply-shipment-boxes"),
    path("<int:pk>/actions/customs-declare/", views.internal_shipment_customs, name="supply-shipment-customs"),
    path("<int:pk>/actions/dispatch/", views.internal_shipment_dispatch, name="supply-shipment-dispatch"),
    path("<int:pk>/actions/port-arrival/", views.internal_shipment_port_arrival, name="supply-shipment-port-arrival"),
    path("<int:pk>/actions/warehouse-arrival/", views.internal_shipment_warehouse_arrival, name="supply-shipment-warehouse-arrival"),
    path("<int:pk>/actions/warehouse-clearance/", views.internal_shipment_clearance, name="supply-shipment-clearance"),
    path("<int:pk>/actions/exception/", views.internal_shipment_exception, name="supply-shipment-exception"),
    path("<int:pk>/actions/cancel/", views.internal_shipment_cancel, name="supply-shipment-cancel"),
]
