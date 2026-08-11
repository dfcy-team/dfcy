from django.urls import path

from . import api_views as views


urlpatterns = [
    path("assignments/", views.supplier_assignment_collection, name="supplier-consolidation-assignments"),
    path("assignments/<int:allocation_id>/", views.supplier_assignment_detail, name="supplier-consolidation-assignment"),
    path("assignments/<int:allocation_id>/actions/submit-handover/", views.supplier_assignment_handover, name="supplier-consolidation-submit-handover"),
    path("assignments/<int:allocation_id>/attachments/upload-sessions/", views.supplier_attachment_upload_session, name="supplier-attachment-upload-session"),
    path("attachments/<int:attachment_id>/actions/finalize/", views.supplier_attachment_finalize, name="supplier-attachment-finalize"),
    path("attachments/<int:attachment_id>/status/", views.supplier_attachment_status, name="supplier-attachment-status"),
    path("attachments/<int:attachment_id>/download-ticket/", views.supplier_attachment_download_ticket, name="supplier-attachment-download-ticket"),
]
