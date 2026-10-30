"""Read-only release companion; run with manage.py shell. Never grants or sends.

exec(open('scripts/inspect_advertising_report_grants.py', encoding='utf-8').read())
Regenerate this plan immediately before applying authorization through the audited UI/API.
"""
import json

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from apps.masterdata.models import StoreMaster
from apps.permissions.authorization import authorization_version
from apps.permissions.resource_policies import RESOURCE_DEFINITIONS
from apps.reports.advertising_dataset import filter_advertising_stores


def inspect_plan():
    targets = []
    for username, expected_id in (("lanx", 59), ("zhanzq", 60)):
        user = get_user_model().objects.get(
            pk=expected_id, username=username, tenant_id=1, is_active=True, user_type="internal",
        )
        related = StoreMaster.objects.filter(tenant_id=user.tenant_id).filter(Q(operator=user) | Q(leader=user))
        store_ids = sorted(set(filter_advertising_stores(user, related).values_list("pk", flat=True)))
        targets.append({
            "user_id": user.pk, "username": username,
            "authorization_version": authorization_version(user),
            "role_code": "feishu-ads-report-" + username,
            "action_permission_codes": ["reports.view"],
            "menu_permission_codes": [], "field_permission_codes": [],
            "scope_type": "custom", "scope_config": {"store_ids": store_ids},
            "resource_policies": [{"resource_code": "reports.advertising", "permission_code": "*",
                                   "scope_type": "custom", "config": {"store_ids": store_ids}}],
            "existing_position_tenant_bindings": user.user_roles.filter(source="position", context_key="tenant").count(),
            "ready": bool(store_ids) and not user.user_roles.filter(source="position", context_key="tenant").exists(),
        })
    return {"status": "READ_ONLY_PLAN_NOT_APPLIED", "generated_at": timezone.now().isoformat(),
            "resource_registered": "reports.advertising" in RESOURCE_DEFINITIONS,
            "database_writes": 0, "messages_sent": 0, "targets": targets,
            "apply_method": "Audited role/authorization UI or API; add binding, never replace existing roles",
            "stop_if": "Empty scope, existing position tenant bindings, changed authorization version/store relationships, or candidate not deployed"}


print("RESULT=" + json.dumps(inspect_plan(), ensure_ascii=True))
