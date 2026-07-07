import pytest
from django.conf import settings

from apps.accounts.models import CustomUser
from apps.audit.models import (
    ApprovalLog,
    DataImportLog,
    NotificationMessage,
    OperationLog,
    SystemExceptionLog,
)
from apps.audit.services import write_exception_log, write_operation_log
from apps.files.models import AttachmentFile
from apps.tenants.models import Tenant


@pytest.mark.django_db
def test_operation_log_and_helper_can_record_changes():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = CustomUser.objects.create_user(
        username="operator",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )

    log = write_operation_log(
        tenant=tenant,
        user=user,
        module="accounts",
        action="update",
        object_type="CustomUser",
        object_id=user.id,
        before_data={"phone": ""},
        after_data={"phone": "13800000000"},
        ip_address="127.0.0.1",
        user_agent="pytest",
    )

    assert log.id is not None
    assert log.tenant == tenant
    assert log.user == user
    assert log.after_data == {"phone": "13800000000"}


@pytest.mark.django_db
def test_exception_log_helper_can_record_exception_context():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")

    try:
        raise ValueError("example failure")
    except ValueError as exc:
        log = write_exception_log(module="tests", exception=exc, tenant=tenant, context={"case": "unit"})

    assert log.exception_type == "ValueError"
    assert log.message == "example failure"
    assert log.context == {"case": "unit"}
    assert log.severity == SystemExceptionLog.Severity.ERROR


@pytest.mark.django_db
def test_audit_supporting_logs_can_be_created():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = CustomUser.objects.create_user(
        username="auditor",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )

    approval = ApprovalLog.objects.create(
        tenant=tenant,
        user=user,
        business_type="purchase_request",
        business_id="PR-001",
        action="approve",
        status="approved",
    )
    notification = NotificationMessage.objects.create(
        tenant=tenant,
        user=user,
        title="Approval finished",
        message="Purchase request approved.",
        message_type="approval",
    )
    data_import = DataImportLog.objects.create(
        tenant=tenant,
        import_type="inventory",
        file_name="inventory.xlsx",
        status=DataImportLog.Status.SUCCESS,
        total_count=10,
        success_count=10,
        created_by=user,
    )

    assert approval.status == "approved"
    assert notification.status == NotificationMessage.Status.UNREAD
    assert data_import.success_count == 10


@pytest.mark.django_db
def test_attachment_file_can_be_created_with_local_media_settings():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = CustomUser.objects.create_user(
        username="uploader",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )

    attachment = AttachmentFile.objects.create(
        tenant=tenant,
        file_name="proof.png",
        file_path="uploads/proof.png",
        file_type="image/png",
        file_size=1024,
        uploaded_by=user,
        business_type="rpa_task",
        business_id="1",
    )

    assert attachment.id is not None
    assert attachment.is_private is True
    assert settings.MEDIA_URL == "/media/"
    assert str(settings.MEDIA_ROOT).endswith("media")


def test_log_models_and_attachment_model_exist():
    assert OperationLog is not None
    assert ApprovalLog is not None
    assert NotificationMessage is not None
    assert DataImportLog is not None
    assert SystemExceptionLog is not None
    assert AttachmentFile is not None
