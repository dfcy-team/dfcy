import io
import csv
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from apps.finance.imports import templates
from apps.finance.models import BankReceiptImport, FinanceAuditLog, PlatformStatement, WithdrawalRecord
from apps.permissions.models import DataScope, Permission, Role
from apps.tenants.models import Tenant
from tests.test_phase2_finance_reconciliation import create_user, grant_finance_access


@pytest.fixture
def client_user(db):
    tenant = Tenant.objects.create(name="Imports", code="csv-imports")
    user = create_user(tenant, "csv-importer")
    grant_finance_access(user)
    client = APIClient(); client.force_authenticate(user)
    return client, user


def upload(kind, rows):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=templates()[kind])
    writer.writeheader(); writer.writerows(rows)
    return SimpleUploadedFile("facts.csv", output.getvalue().encode("utf-8"), content_type="text/csv")


def statement(key="ST-1", currency="USD"):
    return dict(platform="shopee", statement_no=key, currency=currency, period_start="2026-10-01", period_end="2026-10-10", gross_amount="100", fee_amount="10", net_amount="90")


def preview(client, kind, rows):
    return client.post("/api/finance/imports/", {"kind":kind, "file":upload(kind, rows)}, format="multipart")


def commit(client, kind, rows):
    pre = preview(client, kind, rows)
    assert pre.status_code == 200, pre.data
    return client.post("/api/finance/imports/", {"kind":kind,"mode":"commit","sha256":pre.data["data"]["sha256"],"file":upload(kind, rows)}, format="multipart")


def test_preview_is_readonly_and_commit_is_idempotent(client_user):
    client, user = client_user
    rows=[statement()]
    assert preview(client, "statements", rows).status_code == 200
    assert PlatformStatement.objects.count() == 0
    assert FinanceAuditLog.objects.count() == 0
    first = commit(client,"statements",rows)
    assert first.status_code == 201
    assert first.data["data"]["created"] == 1
    second = commit(client,"statements",rows)
    assert second.data["data"]["skipped"] == 1
    assert PlatformStatement.objects.count() == 1
    obj = PlatformStatement.objects.get()
    assert obj.net_amount == Decimal("90.00") and obj.source_type == "manual_import"
    assert client.get("/api/finance/imports/").data["data"]["history"][0]["skipped"] == 1


def test_invalid_batch_and_conflicts_never_partially_write(client_user):
    client, _ = client_user
    invalid = statement("ST-2"); invalid["net_amount"] = "85"
    assert preview(client,"statements",[statement(),invalid]).status_code == 400
    assert PlatformStatement.objects.count() == 0
    assert preview(client,"statements",[statement(),statement()]).status_code == 400
    commit(client,"statements",[statement()])
    conflict = statement(); conflict.update(gross_amount="110",net_amount="100")
    assert preview(client,"statements",[statement("NEW"),conflict]).status_code == 400
    assert PlatformStatement.objects.count() == 1
    assert not PlatformStatement.objects.filter(statement_no="NEW").exists()


def test_csv_upload_bounds_and_hash_change_are_rejected(client_user):
    client, _=client_user
    assert preview(client,"statements",[statement(str(i)) for i in range(501)]).status_code == 400
    payload={"kind":"statements","file":SimpleUploadedFile("big.csv",b'x'*(1024*1024+1))}
    assert client.post('/api/finance/imports/',payload,format='multipart').status_code == 400
    malformed={"kind":"statements","file":SimpleUploadedFile("invalid.csv",b'x' * (csv.field_size_limit()+1) + b'\n')}
    assert client.post('/api/finance/imports/',malformed,format='multipart').status_code == 400
    pre = preview(client,"statements",[statement()]).data['data']
    result=client.post('/api/finance/imports/',{'kind':'statements','mode':'commit','sha256':pre['sha256'],'file':upload('statements',[statement('CHANGED')])},format='multipart')
    assert result.status_code == 400 and PlatformStatement.objects.count() == 0


def test_scope_cannot_be_bypassed_by_import(client_user):
    client,user=client_user
    scope=DataScope.objects.filter(tenant=user.tenant).first()
    scope.scope_type=DataScope.ScopeType.CUSTOM;scope.config={'platforms':['shopee'],'currencies':['USD']};scope.save()
    assert preview(client,'statements',[statement(currency='EUR')]).status_code == 403
    row={'reference_no':'R-1','import_batch_no':'B-1','masked_account':'****1234','currency':'USD','receipt_amount':'90','receipt_date':'2026-10-10'}
    # A platform-limited role cannot infer bank ownership from a currency.
    assert preview(client,'bank-receipts',[row]).status_code == 403
    assert PlatformStatement.objects.count() == 0 and BankReceiptImport.objects.count() == 0


def test_receipt_masking_and_withdrawal_time_validation(client_user):
    client,_=client_user
    receipt={'reference_no':'R-1','import_batch_no':'B-1','masked_account':'1234567890','currency':'USD','receipt_amount':'90','receipt_date':'2026-10-10'}
    assert preview(client,'bank-receipts',[receipt]).status_code == 400
    receipt['masked_account']='****1234'
    receipt['receipt_amount']='0'
    assert preview(client,'bank-receipts',[receipt]).status_code == 400
    receipt['receipt_amount']='90'
    assert commit(client,'bank-receipts',[receipt]).status_code == 201
    withdrawal={'platform':'shopee','withdrawal_no':'W-1','currency':'USD','requested_amount':'100','expected_amount':'90','requested_at':'2026-10-09T12:00:00Z','completed_at':'2026-10-10T12:00:00Z'}
    assert commit(client,'withdrawals',[withdrawal]).status_code == 201
    assert WithdrawalRecord.objects.get().status == 'completed'
    withdrawal['withdrawal_no']='W-2';withdrawal['completed_at']='2026-10-08T12:00:00Z'
    assert preview(client,'withdrawals',[withdrawal]).status_code == 400
    withdrawal['completed_at']='2026-10-10T12:00:00'
    assert preview(client,'withdrawals',[withdrawal]).status_code == 400


def test_import_requires_import_permission_and_history_is_personal(client_user):
    client,user=client_user
    commit(client,'statements',[statement()])
    other=create_user(user.tenant,'csv-other');grant_finance_access(other,['finance.view'])
    second=APIClient();second.force_authenticate(other)
    assert second.get('/api/finance/imports/').status_code == 403
    assert preview(second,'statements',[statement('DENIED')]).status_code == 403
    Role.objects.get(code=f"finance-viewer-{other.id}").permissions.add(Permission.objects.get(code="finance.import"))
    assert second.get('/api/finance/imports/').data['data']['history'] == []
