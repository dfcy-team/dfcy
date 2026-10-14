from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import close_old_connections, connection, connections
from django.apps import apps
from django.db.migrations.state import ProjectState
from rest_framework.exceptions import ValidationError
from apps.accounts.models import CustomUser
from apps.finance.models import FinanceAuditLog, ReconciliationMatch
from apps.finance.services import confirm_match, create_manual_match, reject_match
from apps.tenants.models import Tenant
from tests.test_finance_remediation import all_scopes, finance_rows, user_with_scopes

pytestmark=pytest.mark.django_db(transaction=True)


def mysql_only():
    if connection.vendor != 'mysql':
        pytest.skip('Requires isolated MySQL/InnoDB row locks.')


def run_race(user, actions):
    barrier=Barrier(2)
    def invoke(action):
        close_old_connections()
        try:
            actor=CustomUser.objects.get(pk=user.pk)
            barrier.wait(timeout=10)
            try:
                action(actor)
                return 'success'
            except ValidationError:
                return 'rejected'
        finally:
            connections.close_all()
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures=[executor.submit(invoke,action) for action in actions]
        return [future.result(timeout=30) for future in futures]


def test_mysql_simultaneous_same_source_creation_has_one_winner():
    mysql_only()
    tenant=Tenant.objects.create(name='MySQL race',code='mysql-create-race')
    user,_=user_with_scopes(tenant,'mysql-race-user',all_scopes())
    statement,withdrawal,receipt=finance_rows(tenant)
    action=lambda actor:create_manual_match(actor.tenant,actor,statement.pk,withdrawal.pk,receipt.pk)
    assert sorted(run_race(user,[action,action]))==['rejected','success']
    assert ReconciliationMatch.objects.count()==1
    assert FinanceAuditLog.objects.filter(action='create_manual_reconciliation_match').count()==1


def test_mysql_different_statements_cannot_share_one_receipt():
    mysql_only()
    tenant=Tenant.objects.create(name='MySQL receipt race',code='mysql-receipt-race')
    user,_=user_with_scopes(tenant,'mysql-receipt-user',all_scopes())
    first,withdrawal,receipt=finance_rows(tenant)
    second,other,_=finance_rows(tenant,platform='shopee')
    one=lambda actor:create_manual_match(actor.tenant,actor,first.pk,withdrawal.pk,receipt.pk)
    two=lambda actor:create_manual_match(actor.tenant,actor,second.pk,other.pk,receipt.pk)
    assert sorted(run_race(user,[one,two]))==['rejected','success']
    assert ReconciliationMatch.objects.count()==1


def test_mysql_simultaneous_confirm_and_reject_has_one_final_state():
    mysql_only()
    tenant=Tenant.objects.create(name='MySQL review race',code='mysql-review-race')
    user,_=user_with_scopes(tenant,'mysql-review-user',all_scopes())
    statement,withdrawal,receipt=finance_rows(tenant)
    match=create_manual_match(tenant,user,statement.pk,withdrawal.pk,receipt.pk)
    one=lambda actor:confirm_match(ReconciliationMatch.objects.get(pk=match.pk),actor)
    two=lambda actor:reject_match(ReconciliationMatch.objects.get(pk=match.pk),actor,'wrong reference')
    assert sorted(run_race(user,[one,two]))==['rejected','success']
    match.refresh_from_db();statement.refresh_from_db();receipt.refresh_from_db()
    assert match.status in ('confirmed','rejected')
    assert FinanceAuditLog.objects.filter(action__in=['confirm_reconciliation_match','reject_reconciliation_match']).count()==1
    assert (receipt.status=='matched')==(match.status=='confirmed')
    assert (statement.status=='matched')==(match.status=='confirmed')


def test_mysql_finance_index_migration_forward_and_reverse():
    mysql_only()
    import importlib
    from apps.finance.models import PlatformFinanceTransaction
    migration=importlib.import_module('apps.finance.migrations.0005_finance_query_indexes').Migration('0005','finance')
    state=ProjectState.from_apps(apps)
    # --nomigrations syncs the final schema. Remove only this candidate's two
    # indexes to reproduce the finance table at the deployed baseline.
    with connection.schema_editor() as editor:
        for op in migration.operations:
            editor.remove_index(PlatformFinanceTransaction,op.index)
        for op in migration.operations:
            op.database_forwards('finance',editor,state,state)
    with connection.cursor() as cursor:
        indexes=connection.introspection.get_constraints(cursor,PlatformFinanceTransaction._meta.db_table)
    assert all(op.index.name in indexes for op in migration.operations)
    with connection.schema_editor() as editor:
        for op in reversed(migration.operations):
            op.database_backwards('finance',editor,state,state)
        for op in migration.operations:
            op.database_forwards('finance',editor,state,state)
