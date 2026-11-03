"""Collect a named store/month without modifying local business facts."""
import json
import re
from calendar import monthrange
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from apps.integrations.models import MarketplaceStoreAuthorization, marketplace_authorization_api_type
from apps.integrations.readonly_clients import ShopeeReadonlyClient


class Command(BaseCommand):
    help = "Read CB Shopee payout/billing data for reconciliation; no ledger/database writes."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--store-code", required=True)
        parser.add_argument("--authorization-id", type=int, required=True)
        parser.add_argument("--month", required=True, help="Payout month in the store's local timezone (YYYY-MM).")
        parser.add_argument("--output", required=True, help="New JSON file; existing files are never overwritten.")

    def handle(self, *args, **options):
        if not re.fullmatch(r"\d{4}-\d{2}", options["month"]):
            raise CommandError("Month must use YYYY-MM.")
        try:
            year, month = map(int, options["month"].split("-"))
            datetime(year, month, 1)
        except ValueError:
            raise CommandError("Invalid month.") from None
        output = Path(options["output"]).resolve()
        if output.exists() or not output.parent.is_dir():
            raise CommandError("Output must be a new file in an existing directory.")
        # Enforce read-only at the database session, not just by convention.
        with connection.cursor() as cursor:
            vendor = connection.vendor
            if vendor == "mysql":
                cursor.execute("SET SESSION TRANSACTION READ ONLY")
            elif vendor == "postgresql":
                cursor.execute("SET default_transaction_read_only = on")
            elif vendor == "sqlite":
                cursor.execute("PRAGMA query_only = ON")
            else:
                raise CommandError("Database read-only mode is unsupported.")
        try:
            with transaction.atomic():
                authorization = MarketplaceStoreAuthorization.objects.select_related("store", "integration_config").filter(
                    pk=options["authorization_id"], tenant_id=options["tenant_id"],
                    store__code=options["store_code"], platform="shopee", status="active",
                ).first()
                if (authorization is None
                        or marketplace_authorization_api_type(authorization.integration_config) != "marketplace"
                        or authorization.integration_config.tenant_id != authorization.tenant_id
                        or authorization.store.tenant_id != authorization.tenant_id):
                    raise CommandError("No matching active marketplace authorization in this tenant/store scope.")
                zone = ZoneInfo(authorization.store.timezone)
                start = datetime(year, month, 1, tzinfo=zone)
                end = datetime(year, month, monthrange(year, month)[1], 23, 59, 59, tzinfo=zone)
                client = ShopeeReadonlyClient(authorization.integration_config, authorization)
                client.resource_type = "settlement_bill"
                result = client.fetch_payout_finance({"time_from": int(start.timestamp()),
                                                     "time_to": int(end.timestamp()), "page_size": 100})
                result.update(store_code=authorization.store.code, tenant_id=authorization.tenant_id,
                              month=options["month"], timezone=authorization.store.timezone,
                              collected_at=datetime.now().astimezone().isoformat(), ledger_writes=0)
            with output.open("x", encoding="utf-8") as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2)
        finally:
            # Do not leak a changed session policy into a reused Django connection.
            connection.close()
        self.stdout.write(json.dumps({"store": result["store_code"], "month": result["month"],
                                      "payout_count": len(result["payouts"]),
                                      "transaction_count": len(result["transactions"]),
                                      "unclassified_count": result["unclassified_count"],
                                      "reconciled": result["reconciled"],
                                      "summary": result["summary"], "ledger_writes": 0}, ensure_ascii=False))
