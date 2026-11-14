"""Shared draft allocator for the sampling resolver and CSV confirmation."""

import hashlib

from django.db import IntegrityError, transaction
from rest_framework.exceptions import ValidationError

from .models import Influencer


def allocate_sample_nickname_draft(*, user, nickname, request_key=""):
    """Allocate only a nickname; callers hold the tenant lock and resolve first."""
    nickname_identity = request_key or f"nickname:{nickname.casefold()}"
    digest = hashlib.sha256(
        f"{user.tenant_id}:nickname-draft:{nickname_identity}".encode("utf-8")
    ).hexdigest()[:20]
    base_code = f"draft-{digest}"
    for suffix in range(100):
        code = base_code if suffix == 0 else f"{base_code[:72]}-{suffix}"
        try:
            with transaction.atomic():
                candidate, created = Influencer.objects.get_or_create(
                    tenant_id=user.tenant_id,
                    code=code,
                    defaults={
                        "name": nickname,
                        "handle": "",
                        "platform": "TikTok",
                        "status": Influencer.Status.ACTIVE,
                    },
                )
        except IntegrityError:
            continue
        if created or (
            candidate.platform.lower() == "tiktok"
            and not candidate.handle
            and candidate.name.casefold() == nickname.casefold()
        ):
            return candidate, created
    raise ValidationError({"nickname": "无法创建当前租户的达人档案。"})
