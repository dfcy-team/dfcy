from unittest.mock import MagicMock, patch

import pytest
from django.core.exceptions import ValidationError

from apps.influencers.models import Influencer


@pytest.mark.parametrize("vendor,columns", [
    ("sqlite", ()), ("mysql", ()), ("mysql", ("is_deleted",)),
    ("mysql", ("deletion_previous_status",)),
    ("mysql", ("is_deleted", "deletion_previous_status")),
])
def test_creator_insert_contract(vendor, columns):
    obj = Influencer()
    db, manager = MagicMock(), MagicMock()
    db.vendor = vendor
    cursor = db.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [(column,) for column in columns]
    original = [obj._meta.get_field("name")]
    with patch("apps.influencers.models.connections", {"default": db}):
        if len(columns) == 1:
            with pytest.raises(ValidationError, match="Incomplete creator archive schema"):
                obj._do_insert(manager, "default", original, [], False)
            manager._insert.assert_not_called()
            return
        obj._do_insert(manager, "default", original, [], False)
    assert db.cursor.call_count == int(vendor == "mysql")
    actual = manager._insert.call_args.kwargs["fields"]
    assert [f.name for f in actual] == ["name", *columns]
    assert len(original) == 1
    if columns:
        assert obj.is_deleted is False and obj.deletion_previous_status == ""
        assert set(columns).isdisjoint(f.name for f in obj._meta.concrete_fields)
