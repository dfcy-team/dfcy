from django.urls import path

from . import api_views as views


urlpatterns = [
    path("consolidations/assignments/", views.miniapp_assignment_collection, name="miniapp-consolidation-assignments"),
    path("consolidations/assignments/<int:allocation_id>/", views.miniapp_assignment_detail, name="miniapp-consolidation-assignment"),
    path("consolidations/assignments/<int:allocation_id>/actions/submit-handover/", views.miniapp_assignment_handover, name="miniapp-consolidation-submit-handover"),
    path("consolidations/assignments/<int:allocation_id>/attachments/upload-sessions/", views.miniapp_attachment_upload_session, name="miniapp-attachment-upload-session"),
    path("consolidations/attachments/<int:attachment_id>/actions/finalize/", views.miniapp_attachment_finalize, name="miniapp-attachment-finalize"),
    path("consolidations/attachments/<int:attachment_id>/status/", views.miniapp_attachment_status, name="miniapp-attachment-status"),
    path("consolidations/attachments/<int:attachment_id>/download-ticket/", views.miniapp_attachment_download_ticket, name="miniapp-attachment-download-ticket"),
]
