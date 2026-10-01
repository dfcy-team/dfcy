"""Permission lifecycle rules shared by runtime and administration.

Historical rows and role links remain stored. Only inactive/retired metadata
disables authorization; hiding navigation alone does not revoke an action.
"""
from django.db.models import Q

from .models import Permission

INACTIVE_STATUSES = ("inactive", "retired")


def inactive_permissions(queryset=None):
    queryset = Permission.objects.all() if queryset is None else queryset
    return queryset.filter(
        Q(metadata__registry_status__in=INACTIVE_STATUSES)
        | Q(metadata__status__in=INACTIVE_STATUSES)
    )


def effective_permissions(queryset=None):
    queryset = Permission.objects.all() if queryset is None else queryset
    # Positive subquery is important on MySQL: NOT(JSON missing key = value)
    # evaluates to NULL and would otherwise hide legacy/active catalog rows.
    return queryset.exclude(pk__in=inactive_permissions().values("pk"))


def permission_is_effective(metadata):
    metadata = metadata if isinstance(metadata, dict) else {}
    return not any(metadata.get(key) in INACTIVE_STATUSES for key in ("registry_status", "status"))


def inactive_permission_codes(cache=None):
    key = ("inactive_permission_codes",)
    if cache is not None and key in cache:
        return cache[key]
    codes = set(inactive_permissions().values_list("code", flat=True))
    if cache is not None:
        cache[key] = codes
    return codes
