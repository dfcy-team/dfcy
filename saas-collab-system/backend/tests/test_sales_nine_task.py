from unittest.mock import patch

import pytest
from django.test import override_settings
from apps.sales_management.tasks import capture_due_sales_nine
from tests.test_sales_realtime_board import _fixture


def test_snapshot_task_default_off_and_invalid_allowlist_do_not_query_database():
    # No django_db marker: any accidentally introduced query fails this test.
    with override_settings(SALES_NINE_SNAPSHOT_ENABLED=False):
        assert capture_due_sales_nine()['status'] == 'disabled'
    for values in [[], ['bad'], ['-1'], ['1'] * 101, ['9' * 40]]:
        with override_settings(SALES_NINE_SNAPSHOT_ENABLED=True, SALES_NINE_SNAPSHOT_STORE_IDS=values):
            assert capture_due_sales_nine()['status'] == 'invalid_allowlist'


@pytest.mark.django_db
def test_enabled_capture_task_only_visits_explicitly_allowlisted_stores():
    user, tenant, platform, store, run, client = _fixture('nine-task-scope')
    other = _fixture('nine-task-other')
    with override_settings(SALES_NINE_SNAPSHOT_ENABLED=True, SALES_NINE_SNAPSHOT_STORE_IDS=[str(store.pk)]):
        with patch('apps.sales_management.nine_snapshot_capture.capture_store', return_value=(None, False)) as capture:
            assert capture_due_sales_nine()['created'] == 0
    assert capture.call_count == 1
    assert capture.call_args.args[0].pk == store.pk
