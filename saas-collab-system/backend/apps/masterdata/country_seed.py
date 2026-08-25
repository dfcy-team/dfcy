COUNTRY_SITES = (
    {
        "code": "PH",
        "name": "Philippines",
        "country_code": "PH",
        "currency": "PHP",
        "timezone": "Asia/Manila",
    },
    {
        "code": "TH",
        "name": "Thailand",
        "country_code": "TH",
        "currency": "THB",
        "timezone": "Asia/Bangkok",
    },
    {
        "code": "MY",
        "name": "Malaysia",
        "country_code": "MY",
        "currency": "MYR",
        "timezone": "Asia/Kuala_Lumpur",
    },
)


def seed_country_sites(*, tenant, model):
    for site in COUNTRY_SITES:
        model.objects.update_or_create(
            tenant=tenant,
            code=site["code"],
            defaults={**site, "platform": None, "status": "active"},
        )
