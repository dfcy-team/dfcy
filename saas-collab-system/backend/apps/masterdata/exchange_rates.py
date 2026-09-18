"""Daily CNY reference rates with a fixed, audited two-source fallback."""
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.request import Request, urlopen

from django.db import transaction
from django.utils import timezone

from .models import CountrySiteMaster


SOURCES = (
    ("jsdelivr", "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/cny.json"),
    ("cloudflare", "https://latest.currency-api.pages.dev/v1/currencies/cny.json"),
)


class ExchangeRateRefreshError(RuntimeError):
    pass


def fetch_cny_rates(*, opener=urlopen, timeout=12):
    failures = []
    for source, url in SOURCES:
        try:
            request = Request(url, headers={"Accept": "application/json", "User-Agent": "dfcy-exchange-rate/1.0"})
            with opener(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            rate_date = date.fromisoformat(str(payload.get("date") or ""))
            raw_rates = payload.get("cny")
            if not isinstance(raw_rates, dict):
                raise ValueError("missing cny rate map")
            rates = {}
            for code, value in raw_rates.items():
                normalized = str(code or "").strip().upper()
                if len(normalized) != 3 or not normalized.isascii() or not normalized.isalpha():
                    continue
                try:
                    rate = Decimal(str(value))
                except (InvalidOperation, TypeError, ValueError):
                    continue
                if rate > 0:
                    rates[normalized] = rate
            rates["CNY"] = Decimal("1")
            if len(rates) < 2:
                raise ValueError("empty cny rate map")
            return {"date": rate_date, "rates": rates, "source": source}
        except Exception as exc:
            failures.append(type(exc).__name__)
    raise ExchangeRateRefreshError("CNY reference-rate sources are unavailable: " + ", ".join(failures))


def refresh_country_exchange_rates(*, tenant=None, opener=urlopen):
    result = fetch_cny_rates(opener=opener)
    rows = CountrySiteMaster.objects.all()
    if tenant is not None:
        rows = rows.filter(tenant=tenant)
    now = timezone.now()
    changed = []
    missing = set()
    for row in rows:
        currency = str(row.currency or "").strip().upper()
        rate = result["rates"].get(currency)
        if rate is None:
            if currency:
                missing.add(currency)
            continue
        row.cny_exchange_rate = rate
        row.exchange_rate_date = result["date"]
        row.exchange_rate_source = result["source"]
        row.exchange_rate_updated_at = now
        changed.append(row)
    with transaction.atomic():
        CountrySiteMaster.objects.bulk_update(
            changed,
            ["cny_exchange_rate", "exchange_rate_date", "exchange_rate_source", "exchange_rate_updated_at"],
        )
    return {
        "updated": len(changed),
        "missing": sorted(missing),
        "date": result["date"].isoformat(),
        "source": result["source"],
    }


def tenant_cny_rates(tenant):
    rates = {"CNY": {"rate": Decimal("1"), "date": None, "source": "identity"}}
    rows = CountrySiteMaster.objects.filter(
        tenant=tenant,
        cny_exchange_rate__isnull=False,
    ).exclude(currency="").order_by("currency", "-exchange_rate_date", "id")
    for row in rows:
        code = row.currency.upper()
        rates.setdefault(
            code,
            {"rate": row.cny_exchange_rate, "date": row.exchange_rate_date, "source": row.exchange_rate_source},
        )
    return rates
