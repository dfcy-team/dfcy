import io

import pytest
from PIL import Image
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.exceptions import PermissionDenied

from apps.permissions.models import Permission, Role
from apps.sales_management.registration_import import process_group
from tests.test_order_registrations import context

pytestmark = pytest.mark.django_db


def _group(store, order, group_id):
    identity = (store.code, order.external_order_id, group_id)
    group = {"errors": [], "rows": [2], "data": [{"reason": "增加商品", "note": "", "action": "增加",
            "new_sku": "001", "add_quantity": 1, "old_sku": "", "reduce_quantity": ""}]}
    return identity, group


def test_import_group_uses_cached_real_permission_queries(context):
    user, _, store, order, _ = context
    identity, group = _group(store, order, "CACHE")
    with CaptureQueriesContext(connection) as captured:
        result = process_group(user, "exchange", identity, group, {}, "file", preview=True)
    assert result["valid"]
    # Each grant is represented by the real permission catalog table. A single
    # group should resolve its import grant once even though several helpers require it.
    permission_queries = [q for q in captured.captured_queries if "permissions_permission" in q["sql"].lower()]
    assert permission_queries
    assert len(permission_queries) < 4


def test_import_group_rechecks_permission_in_next_group(context):
    user, _, store, order, _ = context
    identity, group = _group(store, order, "FIRST")
    process_group(user, "exchange", identity, group, {}, "file", preview=True)
    permission = Permission.objects.get(code="sales_management.exchange.import")
    for role in Role.objects.filter(tenant=user.tenant, user_roles__user=user):
        role.permissions.remove(permission)
    next_identity, next_group = _group(store, order, "NEXT")
    with pytest.raises(PermissionDenied):
        process_group(user, "exchange", next_identity, next_group, {}, "file", preview=True)


def test_attachment_count_does_not_repeat_permission_queries(context):
    user, _, store, order, _ = context
    counts = []
    for count in (0, 3):
        identity, group = _group(store, order, f"ATTACH-{count}")
        attachments = {}
        for index in range(count):
            buffer = io.BytesIO()
            Image.new("RGB", (2, 2), (index, 0, 0)).save(buffer, format="PNG")
            attachments[f"{index}.png"] = buffer.getvalue()
        group["data"][0]["attachments"] = ";".join(attachments)
        with CaptureQueriesContext(connection) as captured:
            result = process_group(user, "exchange", identity, group, attachments, "file", preview=True)
        assert result["attachment_count"] == count
        counts.append(sum('"permissions_' in row["sql"].lower() for row in captured.captured_queries))
    assert counts[0] > 0
    assert counts[0] == counts[1]
