from django.db.models import Case, CharField, F, OuterRef, Q, Subquery, When

from .models import TikTokCreatorProfileSnapshot
from .scopes import COUNTRY_NAMES


def with_verified_market(queryset):
    latest = TikTokCreatorProfileSnapshot.objects.filter(
        tenant_id=OuterRef("tenant_id"), influencer_id=OuterRef("pk"),
        external_influencer_id=OuterRef("profile__external_influencer_id"),
    ).order_by("-fetched_at", "-pk").annotate(
        verified_region=Case(
            When(
                identity_status=TikTokCreatorProfileSnapshot.IdentityStatus.MATCHED,
                username__iexact=OuterRef("handle"),
                selection_region__in=tuple(COUNTRY_NAMES),
                then="selection_region",
            ),
            output_field=CharField(),
        ),
    )
    return queryset.annotate(_verified_market=Case(
        When(
            platform__iexact="tiktok", profile__tenant_id=F("tenant_id"),
            then=Subquery(latest.values("verified_region")[:1]),
        ),
        output_field=CharField(),
    ))


def filter_display_market(queryset, value, tenant_id):
    aliases = (value,)
    for code, names in COUNTRY_NAMES.items():
        if value.casefold() in {item.casefold() for item in (code, *names)}:
            aliases = (code, *names)
            break
    legacy = Q()
    for alias in aliases:
        legacy |= Q(profile__market__iexact=alias)
    return queryset.filter(
        Q(_verified_market=aliases[0])
        | (Q(_verified_market__isnull=True, profile__tenant_id=tenant_id) & legacy),
    )


def market_label(region):
    return COUNTRY_NAMES[region][0]
