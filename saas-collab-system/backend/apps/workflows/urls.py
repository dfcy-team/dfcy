from django.urls import path

from . import views


urlpatterns = [
    path("payment-flow-reviewers/", views.payment_flow_reviewers, name="workflow-payment-flow-reviewers"),
    path("payment-flow-departments/", views.payment_flow_departments, name="workflow-payment-flow-departments"),
    path("payment-flows/", views.payment_flow_collection, name="workflow-payment-flow-list"),
    path("payment-flows/<int:pk>/<str:action>/", views.payment_flow_action, name="workflow-payment-flow-action"),
    path("approvals/", views.approval_collection, name="workflow-approval-list"),
    path("approvals/mock/", views.approval_mock_create, name="workflow-approval-mock"),
    path("approvals/<int:pk>/", views.approval_detail, name="workflow-approval-detail"),
    path("approvals/<int:pk>/approve/", views.approval_approve, name="workflow-approval-approve"),
    path("approvals/<int:pk>/reject/", views.approval_reject, name="workflow-approval-reject"),
    path("approvals/<int:pk>/withdraw/", views.approval_withdraw, name="workflow-approval-withdraw"),
    path("exceptions/", views.exception_collection, name="workflow-exception-list"),
    path("exceptions/mock/", views.exception_mock_create, name="workflow-exception-mock"),
    path("exceptions/<int:pk>/", views.exception_detail, name="workflow-exception-detail"),
    path("exceptions/<int:pk>/assign/", views.exception_assign, name="workflow-exception-assign"),
    path("exceptions/<int:pk>/resolve/", views.exception_resolve, name="workflow-exception-resolve"),
    path("exceptions/<int:pk>/close/", views.exception_close, name="workflow-exception-close"),
    path("collaboration-events/", views.collaboration_collection, name="workflow-collaboration-list"),
    path("collaboration-events/<int:pk>/confirm/", views.collaboration_confirm, name="workflow-collaboration-confirm"),
    path("collaboration-events/<int:pk>/reject/", views.collaboration_reject, name="workflow-collaboration-reject"),
]
