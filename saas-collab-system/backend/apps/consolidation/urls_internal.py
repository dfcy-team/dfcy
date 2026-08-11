from django.urls import path

from . import api_views as views


urlpatterns = [
    path("sites/", views.internal_site_collection, name="supply-consolidation-sites"),
    path("sites/<int:pk>/", views.internal_site_detail, name="supply-consolidation-site-detail"),
    path("sites/<int:pk>/actions/deactivate/", views.internal_site_deactivate, name="supply-consolidation-site-deactivate"),
    path("supplier-capabilities/", views.internal_supplier_capability_collection, name="supply-consolidation-supplier-capabilities"),
    path("supplier-capabilities/<int:supplier_id>/", views.internal_supplier_capability_collection, name="supply-consolidation-supplier-capability-detail"),
    path("consolidations/", views.internal_consolidation_collection, name="supply-consolidations"),
    # The frozen contract uses the consolidation prefix itself as the
    # collection endpoint; retain the explicit nested alias for clients that
    # mount this URLConf below ``/supply-chain/``.
    path("", views.internal_consolidation_collection, name="supply-consolidations-root"),
    path("consolidations/<int:pk>/", views.internal_consolidation_detail, name="supply-consolidation-detail"),
    path("<int:pk>/", views.internal_consolidation_detail, name="supply-consolidation-detail-root"),
    path("consolidations/<int:pk>/boxes/", views.internal_consolidation_boxes, name="supply-consolidation-boxes"),
    path("<int:pk>/boxes/", views.internal_consolidation_boxes, name="supply-consolidation-boxes-root"),
    path("consolidations/<int:pk>/boxes/<int:allocation_id>/actions/remove/", views.internal_consolidation_box_remove, name="supply-consolidation-box-remove"),
    path("consolidations/<int:pk>/boxes/<int:allocation_id>/actions/receive/", views.internal_consolidation_receive, name="supply-consolidation-box-receive"),
    path("consolidations/<int:pk>/boxes/<int:allocation_id>/actions/exception/", views.internal_consolidation_exception, name="supply-consolidation-box-exception"),
    path("consolidations/<int:pk>/boxes/<int:allocation_id>/actions/controlled-release/", views.internal_consolidation_controlled_release, name="supply-consolidation-box-controlled-release"),
    path("consolidations/<int:pk>/actions/release/", views.internal_consolidation_release, name="supply-consolidation-release"),
    path("consolidations/<int:pk>/actions/ready/", views.internal_consolidation_ready, name="supply-consolidation-ready"),
    path("consolidations/<int:pk>/actions/transfer/", views.internal_consolidation_transfer, name="supply-consolidation-transfer"),
    path("consolidations/<int:pk>/actions/cancel/", views.internal_consolidation_cancel, name="supply-consolidation-cancel"),
    path("<int:pk>/boxes/<int:allocation_id>/actions/remove/", views.internal_consolidation_box_remove, name="supply-consolidation-box-remove-root"),
    path("<int:pk>/boxes/<int:allocation_id>/actions/receive/", views.internal_consolidation_receive, name="supply-consolidation-box-receive-root"),
    path("<int:pk>/boxes/<int:allocation_id>/actions/exception/", views.internal_consolidation_exception, name="supply-consolidation-box-exception-root"),
    path("<int:pk>/boxes/<int:allocation_id>/actions/controlled-release/", views.internal_consolidation_controlled_release, name="supply-consolidation-box-controlled-release-root"),
    path("<int:pk>/actions/release/", views.internal_consolidation_release, name="supply-consolidation-release-root"),
    path("<int:pk>/actions/ready/", views.internal_consolidation_ready, name="supply-consolidation-ready-root"),
    path("<int:pk>/actions/transfer/", views.internal_consolidation_transfer, name="supply-consolidation-transfer-root"),
    path("<int:pk>/actions/cancel/", views.internal_consolidation_cancel, name="supply-consolidation-cancel-root"),
]
