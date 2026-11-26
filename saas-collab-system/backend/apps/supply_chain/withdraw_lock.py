"""Withdrawal-only fail-fast lock; retain the same tenant serialization boundary."""
from django.db import connection, OperationalError
from apps.common.exceptions import StateConflict
from apps.tenants.models import Tenant


def lock_for_withdrawal(actor):
    options = {'nowait': True} if connection.features.has_select_for_update_nowait else {}
    Tenant.objects.select_for_update(**options).get(pk=actor.tenant_id)


def withdrawal_result(command):
    # command's atomic decorator must exit/rollback before translating database errors.
    try:
        return command()
    except OperationalError as exc:
        if exc.args and exc.args[0] in (1205, 1213, 3572):
            raise StateConflict('同一租户有其他业务正在处理中，本次撤回未完成。请稍后刷新单据状态再操作。') from exc
        raise
