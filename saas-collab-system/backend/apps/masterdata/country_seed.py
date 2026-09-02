"""Idempotent tenant-scoped seed data for common cross-border destinations."""

from django.db import IntegrityError, transaction


# Names are Unicode escaped to keep this source portable across legacy Windows
# code pages. They render as Chinese names at runtime.
COUNTRY_SITE_SEEDS = (
    {"name": "\u4e2d\u56fd", "country_code": "CN", "currency": "CNY", "timezone": "Asia/Shanghai"},
    {"name": "\u65e5\u672c", "country_code": "JP", "currency": "JPY", "timezone": "Asia/Tokyo"},
    {"name": "\u97e9\u56fd", "country_code": "KR", "currency": "KRW", "timezone": "Asia/Seoul"},
    {"name": "\u4e2d\u56fd\u53f0\u6e7e", "country_code": "TW", "currency": "TWD", "timezone": "Asia/Taipei"},
    {"name": "\u65b0\u52a0\u5761", "country_code": "SG", "currency": "SGD", "timezone": "Asia/Singapore"},
    {"name": "\u9a6c\u6765\u897f\u4e9a", "country_code": "MY", "currency": "MYR", "timezone": "Asia/Kuala_Lumpur"},
    {"name": "\u6cf0\u56fd", "country_code": "TH", "currency": "THB", "timezone": "Asia/Bangkok"},
    {"name": "\u8d8a\u5357", "country_code": "VN", "currency": "VND", "timezone": "Asia/Ho_Chi_Minh"},
    {"name": "\u5370\u5ea6\u5c3c\u897f\u4e9a", "country_code": "ID", "currency": "IDR", "timezone": "Asia/Jakarta"},
    {"name": "\u83f2\u5f8b\u5bbe", "country_code": "PH", "currency": "PHP", "timezone": "Asia/Manila"},
    {"name": "\u5370\u5ea6", "country_code": "IN", "currency": "INR", "timezone": "Asia/Kolkata"},
    {"name": "\u6fb3\u5927\u5229\u4e9a", "country_code": "AU", "currency": "AUD", "timezone": "Australia/Sydney"},
    {"name": "\u65b0\u897f\u5170", "country_code": "NZ", "currency": "NZD", "timezone": "Pacific/Auckland"},
    {"name": "\u7f8e\u56fd", "country_code": "US", "currency": "USD", "timezone": "America/New_York"},
    {"name": "\u52a0\u62ff\u5927", "country_code": "CA", "currency": "CAD", "timezone": "America/Toronto"},
    {"name": "\u58a8\u897f\u54e5", "country_code": "MX", "currency": "MXN", "timezone": "America/Mexico_City"},
    {"name": "\u82f1\u56fd", "country_code": "GB", "currency": "GBP", "timezone": "Europe/London"},
    {"name": "\u5fb7\u56fd", "country_code": "DE", "currency": "EUR", "timezone": "Europe/Berlin"},
    {"name": "\u6cd5\u56fd", "country_code": "FR", "currency": "EUR", "timezone": "Europe/Paris"},
    {"name": "\u610f\u5927\u5229", "country_code": "IT", "currency": "EUR", "timezone": "Europe/Rome"},
    {"name": "\u897f\u73ed\u7259", "country_code": "ES", "currency": "EUR", "timezone": "Europe/Madrid"},
    {"name": "\u8377\u5170", "country_code": "NL", "currency": "EUR", "timezone": "Europe/Amsterdam"},
    {"name": "\u6ce2\u5170", "country_code": "PL", "currency": "PLN", "timezone": "Europe/Warsaw"},
    {"name": "\u571f\u8033\u5176", "country_code": "TR", "currency": "TRY", "timezone": "Europe/Istanbul"},
    {"name": "\u963f\u8054\u914b", "country_code": "AE", "currency": "AED", "timezone": "Asia/Dubai"},
    {"name": "\u6c99\u7279\u963f\u62c9\u4f2f", "country_code": "SA", "currency": "SAR", "timezone": "Asia/Riyadh"},
    {"name": "\u5df4\u897f", "country_code": "BR", "currency": "BRL", "timezone": "America/Sao_Paulo"},
)


def _code_for(country_code):
    return f"country-{country_code.lower()}"


def _unique_code(model, tenant, country_code):
    base = _code_for(country_code)
    code = base
    suffix = 2
    while model.objects.filter(tenant=tenant, code=code).exists():
        code = f"{base}-{suffix}"
        suffix += 1
    return code


def seed_country_sites(*, tenant, model=None, seeds=COUNTRY_SITE_SEEDS, dry_run=False):
    """Create missing rows and fill only blank values on existing rows."""
    if model is None:
        from .models import CountrySiteMaster

        model = CountrySiteMaster
    seeds = tuple(seeds)
    created = updated = skipped = 0
    with transaction.atomic():
        for seed in seeds:
            country_code = seed["country_code"].upper()
            row = model.objects.filter(tenant=tenant, country_code__iexact=country_code).order_by("id").first()
            if row is None:
                if dry_run:
                    created += 1
                    continue
                try:
                    # Use a savepoint so a concurrent unique-key collision
                    # does not poison the surrounding seed transaction.
                    with transaction.atomic():
                        model.objects.create(
                            tenant=tenant,
                            code=_unique_code(model, tenant, country_code),
                            name=seed["name"],
                            country_code=country_code,
                            platform=None,
                            currency=seed["currency"],
                            timezone=seed["timezone"],
                            status="active",
                        )
                    created += 1
                    continue
                except IntegrityError:
                    row = model.objects.filter(tenant=tenant, country_code__iexact=country_code).order_by("id").first()
                    if row is None:
                        raise
            updates = {field: seed[field] for field in ("name", "currency", "timezone") if not getattr(row, field, None)}
            if not updates:
                skipped += 1
            elif dry_run:
                updated += 1
            else:
                model.objects.filter(pk=row.pk).update(**updates)
                updated += 1
    return {"created": created, "updated": updated, "skipped": skipped, "total": len(seeds)}
