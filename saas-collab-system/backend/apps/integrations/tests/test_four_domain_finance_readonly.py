from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.finance.models import (
    BankReceiptImport,
    FinanceAuditLog,
    PlatformFinanceTransaction,
    PlatformStatement,
    ReconciliationException,
    ReconciliationMatch,
    WithdrawalRecord,
)
from apps.integrations.readonly_finance import CONTRACTS, query
from apps.integrations.models import (
    MarketplaceStoreAuthorization, PlatformIntegrationConfig, SyncJob, SyncRun, authorization_service_write,
    marketplace_active_identity_key, marketplace_identity_key, marketplace_store_binding_key,
)
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.tenants.models import Tenant


class FinanceReadonlyContractTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(code="FIN-READ-A", name="Finance A")
        self.other = Tenant.objects.create(code="FIN-READ-B", name="Finance B")
        self.user = get_user_model().objects.create_user(
            username="finance-read-a", tenant=self.tenant, user_type="internal",
        )
        self.other_user = get_user_model().objects.create_user(
            username="finance-read-b", tenant=self.other, user_type="internal",
        )

    def make_statement(self, tenant, no, gross, currency="USD"):
        return PlatformStatement.objects.create(
            tenant=tenant, platform="shopee", statement_no=no,
            period_start=date(2026, 1, 1), period_end=date(2026, 1, 31), currency=currency,
            gross_amount=gross, fee_amount="1.00", net_amount=Decimal(gross) - Decimal("1.00"),
            source_type=PlatformStatement.SourceType.MANUAL_IMPORT,
        )

    def make_chain(self, tenant, statement, no, amount):
        withdrawal = WithdrawalRecord.objects.create(
            tenant=tenant, platform=statement.platform, withdrawal_no=f"W-{no}",
            currency=statement.currency, requested_amount=amount, expected_amount=amount,
            requested_at="2026-02-01T00:00:00Z", completed_at="2026-02-02T00:00:00Z",
            status=WithdrawalRecord.Status.COMPLETED,
        )
        receipt = BankReceiptImport.objects.create(
            tenant=tenant, import_batch_no=f"B-{no}", masked_account="****1234",
            currency=statement.currency, receipt_amount=amount, receipt_date=date(2026, 2, 2),
            reference_no=f"R-{no}", status=BankReceiptImport.Status.MATCHED,
        )
        match = ReconciliationMatch.objects.create(
            tenant=tenant, statement=statement, withdrawal=withdrawal, bank_receipt=receipt,
            matched_amount=amount, difference_amount="0.00", status=ReconciliationMatch.Status.CONFIRMED,
        )
        return match

    def make_transaction_source(self, tenant, suffix):
        user = self.user if tenant.pk == self.tenant.pk else self.other_user
        platform_master = PlatformMaster.objects.create(
            tenant=tenant, code=f"finance-platform-{suffix}", name="Shopee", platform_type="shopee",
        )
        store = StoreMaster.objects.create(
            tenant=tenant, platform=platform_master, code=f"finance-store-{suffix}",
            name="Finance store", country_code="PH", currency="PHP",
        )
        config = PlatformIntegrationConfig.objects.create(
            tenant=tenant, platform="shopee", account_alias=f"finance-{suffix}", created_by=user,
        )
        platform_store_id = f"external-store-{suffix}"
        with authorization_service_write():
            authorization = MarketplaceStoreAuthorization.objects.create(
                tenant=tenant, integration_config=config, store=store, platform="shopee", region="PH",
                platform_store_id=platform_store_id,
                platform_identity_key=marketplace_identity_key("shopee", "PH", platform_store_id),
                active_platform_identity_key=marketplace_active_identity_key("shopee", "PH", platform_store_id),
                active_store_binding_key=marketplace_store_binding_key(tenant.pk, "shopee", store.pk),
                merchant_subject_id=f"merchant-{suffix}", credential_id=f"credential-{suffix}",
                token_id=f"token-{suffix}", created_by=user, updated_by=user,
            )
        job = SyncJob.objects.create(tenant=tenant, integration_config=config, resource_type="settlement_bill")
        run = SyncRun.objects.create(
            tenant=tenant, sync_job=job, run_id=f"finance-run-{suffix}", idempotency_key=f"finance-key-{suffix}",
        )
        return store, authorization, run

    def test_contracts_are_explicit_and_all_queries_are_tenant_scoped(self):
        self.assertEqual(set(CONTRACTS), {
            "finance_imports", "finance_analytics", "platform_statements", "finance_transactions", "withdrawal_records",
            "bank_receipts", "reconciliation_exceptions", "reconciliation_matches",
        })
        for resource, (model, fields) in CONTRACTS.items():
            self.assertIn("id", fields, resource)
            self.assertNotIn("tenant_id", fields, resource)
            rows = query(resource, self.tenant.pk)
            # Every contract is iterable and compiles its ORM work at query time.
            list(rows)

    def test_finance_imports_project_only_fixed_audit_keys(self):
        FinanceAuditLog.objects.create(
            tenant=self.tenant, actor=self.user, action="import_finance_csv",
            object_type="FinanceImportBatch", object_id="hash-a",
            masked_detail={"kind": "statements", "rows": 3, "created": 2, "skipped": 1, "filename": "secret.csv"},
        )
        FinanceAuditLog.objects.create(
            tenant=self.tenant, actor=self.user, action="import_finance_csv",
            object_type="FinanceImportBatch", object_id="hash-b",
            masked_detail={"kind": "withdrawals", "rows": 1, "created": 1, "skipped": 0},
        )
        FinanceAuditLog.objects.create(
            tenant=self.other, actor=self.user, action="import_finance_csv",
            object_type="FinanceImportBatch", object_id="hash-c",
            masked_detail={"kind": "bank-receipts", "rows": 1, "created": 1, "skipped": 0},
        )
        rows = list(query("finance_imports", self.tenant.pk))
        self.assertEqual({row["kind"] for row in rows}, {"statements", "withdrawals"})
        self.assertEqual({(row["rows"], row["created"], row["skipped"]) for row in rows}, {(3, 2, 1), (1, 1, 0)})
        self.assertNotIn("masked_detail", rows[0])

    def test_finance_analytics_sums_by_period_platform_and_currency(self):
        statement = self.make_statement(self.tenant, "S-1", "100.00")
        self.make_statement(self.tenant, "S-2", "40.00")
        # Same period/platform but different currency must stay in its own group.
        other_currency = self.make_statement(self.tenant, "S-3", "25.00", currency="EUR")
        matched = self.make_chain(self.tenant, statement, "1", "70.00")
        self.make_chain(self.tenant, other_currency, "2", "20.00")
        ReconciliationException.objects.create(
            tenant=self.tenant, reconciliation_match=matched,
            exception_type=ReconciliationException.ExceptionType.AMOUNT_DIFFERENCE,
            difference_amount="3.50",
        )
        self.make_statement(self.other, "S-OTHER", "999.00")

        rows = list(query("finance_analytics", self.tenant.pk).order_by("currency"))
        self.assertEqual(len(rows), 2)
        usd, eur = ({row["currency"]: row for row in rows}[currency] for currency in ("USD", "EUR"))
        self.assertEqual((usd["currency"], usd["statement_amount"], usd["matched_amount"]),
                         ("USD", Decimal("140.00"), Decimal("70.00")))
        self.assertEqual((usd["exception_count"], usd["exception_amount"]), (1, Decimal("3.50")))
        self.assertEqual((eur["currency"], eur["statement_amount"], eur["matched_amount"]),
                         ("EUR", Decimal("25.00"), Decimal("20.00")))
        self.assertEqual(eur["exception_count"], 0)

    def test_reconciliation_chain_requires_same_tenant_and_consistent_platform_currency(self):
        statement = self.make_statement(self.tenant, "S-CHAIN", "100.00")
        valid_match = self.make_chain(self.tenant, statement, "VALID", "90.00")
        self.make_chain(self.other, self.make_statement(self.other, "S-B", "20.00"), "OTHER", "20.00")
        foreign_withdrawal = WithdrawalRecord.objects.create(
            tenant=self.other, platform=statement.platform, withdrawal_no="W-CROSS", currency="USD",
            requested_amount="5.00", expected_amount="5.00", requested_at="2026-02-01T00:00:00Z",
        )
        own_receipt = BankReceiptImport.objects.create(
            tenant=self.tenant, import_batch_no="B-CROSS", masked_account="****9999", currency="USD",
            receipt_amount="5.00", receipt_date=date(2026, 2, 2), reference_no="R-CROSS",
        )
        ReconciliationMatch.objects.create(
            tenant=self.tenant, statement=statement, withdrawal=foreign_withdrawal,
            bank_receipt=own_receipt, matched_amount="5.00", difference_amount="0.00",
        )
        ReconciliationException.objects.create(
            tenant=self.tenant, reconciliation_match=valid_match,
            exception_type=ReconciliationException.ExceptionType.AMOUNT_DIFFERENCE,
            difference_amount="1.00",
        )

        self.assertEqual([row["id"] for row in query("reconciliation_matches", self.tenant.pk)], [valid_match.pk])
        exceptions = list(query("reconciliation_exceptions", self.tenant.pk))
        self.assertEqual(len(exceptions), 1)
        self.assertEqual(exceptions[0]["platform"], "shopee")
        self.assertEqual(exceptions[0]["currency"], "USD")

    def test_finance_transactions_project_real_amounts_and_exclude_raw_payload_material(self):
        store, authorization, run = self.make_transaction_source(self.tenant, "own")
        own = PlatformFinanceTransaction.objects.create(
            tenant=self.tenant, store=store, authorization=authorization, source_run=run,
            source_key="private-source-key", platform="shopee", raw_fee_name="Commission",
            fee_code="commission", fee_category=PlatformFinanceTransaction.FeeCategory.PLATFORM_FEE,
            raw_amount="2.3456", signed_amount="-2.3456", currency="PHP",
            occurred_at_utc="2026-02-02T00:00:00Z", business_date=date(2026, 2, 2),
            match_status=PlatformFinanceTransaction.MatchStatus.UNMATCHED,
            normalization_version="v1", payload_hash="f" * 64,
        )
        other_store, other_authorization, other_run = self.make_transaction_source(self.other, "other")
        PlatformFinanceTransaction.objects.create(
            tenant=self.other, store=other_store, authorization=other_authorization, source_run=other_run,
            source_key="other-source-key", platform="shopee", raw_fee_name="Commission",
            fee_code="commission", fee_category=PlatformFinanceTransaction.FeeCategory.PLATFORM_FEE,
            raw_amount="99.0000", signed_amount="-99.0000", currency="PHP",
            occurred_at_utc="2026-02-02T00:00:00Z", business_date=date(2026, 2, 2),
            match_status=PlatformFinanceTransaction.MatchStatus.UNMATCHED,
            normalization_version="v1", payload_hash="e" * 64,
        )
        rows = list(query("finance_transactions", self.tenant.pk))
        self.assertEqual([row["id"] for row in rows], [own.pk])
        self.assertEqual((rows[0]["store_id"], rows[0]["fee_code"], rows[0]["raw_amount"], rows[0]["signed_amount"]),
                         (store.pk, "commission", Decimal("2.3456"), Decimal("-2.3456")))
        fields = set(CONTRACTS["finance_transactions"][1])
        self.assertTrue({"fee_code", "fee_category", "raw_amount", "signed_amount", "currency", "business_date"} <= fields)
        self.assertFalse({"raw_envelope_id", "source_key", "payload_hash", "authorization_id", "source_run_id"} & fields)

