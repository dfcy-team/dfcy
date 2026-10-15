"""Supply-chain calendar dates use the purchasing team's configured time zone."""
from zoneinfo import ZoneInfo
from django.conf import settings
from django.utils import timezone


def business_date():
    return timezone.localdate(timezone.now(), timezone=ZoneInfo(getattr(settings, "SUPPLY_CHAIN_TIME_ZONE", "Asia/Shanghai")))
