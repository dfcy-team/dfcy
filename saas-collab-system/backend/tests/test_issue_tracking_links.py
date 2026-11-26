from types import SimpleNamespace
from unittest.mock import patch
import pytest
from rest_framework.exceptions import PermissionDenied, ValidationError
from apps.issue_tracking.links import can_access_page, can_access_record, validate_context


def actor():
    return SimpleNamespace(pk=1, is_active=True, user_type='internal', is_superuser=False)


def test_menu_access_fails_closed_and_checks_declared_permission():
    registry = {'routes': [{'path': '/supply-chain/purchase-orders', 'permissions': ['supply.v2.view'], 'userTypes': ['internal']}]}
    with patch('apps.issue_tracking.links.load_menu_registry', return_value=registry), patch('apps.issue_tracking.links.check_user_permission', return_value=False):
        assert not can_access_page(actor(), '/supply-chain/purchase-orders')
    with patch('apps.issue_tracking.links.load_menu_registry', return_value=registry), patch('apps.issue_tracking.links.check_user_permission', return_value=True):
        assert can_access_page(actor(), '/supply-chain/purchase-orders')
        assert not can_access_page(actor(), '/unknown')
        assert not can_access_page(actor(), '//evil.test')
        assert not can_access_page(actor(), '/supply-chain/purchase-orders?token=secret')


def test_record_link_requires_known_type_matching_menu_and_both_readers():
    data = {'menu_key': '/supply-chain/purchase-orders', 'page_path': '/supply-chain/purchase-orders', 'record_type': 'purchase_order', 'record_id': '17'}
    with patch('apps.issue_tracking.links.can_access_page', return_value=True), patch('apps.issue_tracking.links.can_access_record', side_effect=[True, False]):
        with pytest.raises(ValidationError):
            validate_context(actor(), data, assignee=actor())
    with patch('apps.issue_tracking.links.can_access_page', return_value=True), patch('apps.issue_tracking.links.can_access_record', return_value=True) as check:
        validate_context(actor(), data, assignee=actor())
        assert check.call_count == 2
    with patch('apps.issue_tracking.links.can_access_page', return_value=True):
        with pytest.raises(ValidationError):
            validate_context(actor(), {**data, 'menu_key': '/workflow/approvals', 'page_path': '/workflow/approvals'})


def test_unknown_record_and_incomplete_identity_rejected():
    assert not can_access_record(actor(), 'arbitrary_model', '17')
    assert not can_access_record(actor(), 'purchase_order', '../../17')
    with pytest.raises(ValidationError):
        validate_context(actor(), {'record_type': 'approval'})
    with patch('apps.issue_tracking.links.can_access_page', return_value=False):
        with pytest.raises(PermissionDenied):
            validate_context(actor(), {'menu_key': '/workflow/approvals', 'page_path': '/workflow/approvals'})


def test_page_cannot_omit_menu_or_mismatch_detail_record():
    with pytest.raises(ValidationError):
        validate_context(actor(), {'page_path': '/workflow/approvals'})
    with patch('apps.issue_tracking.links.can_access_page', return_value=True):
        with pytest.raises(ValidationError):
            validate_context(actor(), {'menu_key': '/workflow/approvals', 'page_path': '/workflow/approvals/22', 'record_type': 'approval', 'record_id': '17'})
