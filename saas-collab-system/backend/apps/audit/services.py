import traceback as traceback_module

from .models import OperationLog, SystemExceptionLog


def write_operation_log(
    *,
    tenant,
    user=None,
    module,
    action,
    object_type="",
    object_id="",
    before_data=None,
    after_data=None,
    ip_address=None,
    user_agent="",
):
    return OperationLog.objects.create(
        tenant=tenant,
        user=user,
        module=module,
        action=action,
        object_type=object_type,
        object_id=str(object_id) if object_id is not None else "",
        before_data=before_data or {},
        after_data=after_data or {},
        ip_address=ip_address,
        user_agent=user_agent,
    )


def write_exception_log(*, module, exception, tenant=None, context=None, severity=SystemExceptionLog.Severity.ERROR):
    return SystemExceptionLog.objects.create(
        tenant=tenant,
        module=module,
        exception_type=exception.__class__.__name__,
        message=str(exception),
        traceback="".join(traceback_module.format_exception(type(exception), exception, exception.__traceback__)),
        context=context or {},
        severity=severity,
    )
