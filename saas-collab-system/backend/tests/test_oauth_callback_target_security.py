"""Synthetic-only regression tests for callback target and current scope binding."""
from urllib.parse import parse_qsl, urlencode, urlsplit
from unittest.mock import Mock

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.integrations.models import MarketplaceStoreAuthorization, OAuthStateSession, PlatformIntegrationConfig
from apps.integrations.marketplace_providers import SyntheticMarketplaceOAuthProvider, synthetic_callback_signature
from apps.masterdata.models import StoreMaster
from apps.permissions.models import DataScope, Role, UserRole
from apps.permissions.ui_p6_scopes import integration_values_allowed
from tests.test_lazada_store_authorization import lazada_context
from tests.test_manual_store_callback import pending, ENDPOINT
from tests.test_mapping_permissions import _permission

pytestmark = pytest.mark.django_db


def complete(client, payload, route):
    if route == 'manual':
        return client.post(ENDPOINT, payload, format='json')
    # The automatic callback intentionally has no authenticated browser user.
    return APIClient().get('/api/internal/integrations/store-authorizations/oauth/callback/lazada/',
        dict(parse_qsl(urlsplit(payload['callback_url']).query)))


def set_shop(payload, shop_id):
    parsed = urlsplit(payload['callback_url'])
    params = dict(parse_qsl(parsed.query))
    params['shop_id'] = shop_id
    params['sign'] = synthetic_callback_signature('lazada', **{k: params[k] for k in ('code', 'state', 'shop_id')})
    return {**payload, 'callback_url': parsed._replace(query=urlencode(params)).geturl()}


def restricted_actor(store, config):
    actor = CustomUser.objects.create_user(username='callback-second-only', tenant=store.tenant,
        user_type=CustomUser.UserType.INTERNAL)
    role = Role.objects.create(tenant=store.tenant, name='Second only', code='second-only', status=Role.Status.ACTIVE)
    role.permissions.add(_permission('integrations.store.authorize'))
    UserRole.objects.create(tenant=store.tenant, user=actor, role=role)
    scope = DataScope.objects.create(tenant=store.tenant, role=role, scope_type=DataScope.ScopeType.CUSTOM,
        config={'store_ids': [store.pk], 'integration_config_ids': [config.pk]})
    return actor, scope


def watch_exchanged_references(monkeypatch):
    new_revoke, previous_revoke = Mock(), Mock()
    original = SyntheticMarketplaceOAuthProvider.exchange_authorization_code
    def exchange(self, payload):
        result = original(self, payload)
        result.update(reference_kind='custody', new_reference_revoker=new_revoke, previous_reference_revoker=previous_revoke,
                      credential_id='synthetic-new-uncommitted-credential', token_id='synthetic-new-uncommitted-token')
        return result
    monkeypatch.setattr(SyntheticMarketplaceOAuthProvider, 'exchange_authorization_code', exchange)
    return new_revoke, previous_revoke


@pytest.mark.parametrize('route', ['manual', 'automatic'])
def test_other_store_identity_cannot_rotate_out_of_scope_authorization(lazada_context, monkeypatch, route):
    client, first, config = lazada_context
    assert complete(client, pending(lazada_context), route).status_code == 200
    existing = MarketplaceStoreAuthorization.objects.get(store=first)
    old = (existing.credential_id, existing.token_id, existing.credential_reference_version)
    second = StoreMaster.objects.create(tenant=first.tenant, platform=first.platform, code='SECOND-MY',
        name='Second', country_code='MY', currency='MYR', timezone='Asia/Kuala_Lumpur')
    actor, _ = restricted_actor(second, config)
    assert not integration_values_allowed(actor, 'integrations.store.authorize', store_id=first.pk, config_id=config.pk)
    assert integration_values_allowed(actor, 'integrations.store.authorize', store_id=second.pk, config_id=config.pk)
    client.force_authenticate(actor)
    payload = set_shop(pending((client, second, config)), existing.platform_store_id)
    new_revoke, previous_revoke = watch_exchanged_references(monkeypatch)
    result = complete(client, payload, route)
    assert result.status_code == 409, result.data
    assert 'OAUTH_STORE_BOUND_CONFLICT' in str(result.data)
    existing.refresh_from_db()
    assert (existing.credential_id, existing.token_id, existing.credential_reference_version) == old
    assert not MarketplaceStoreAuthorization.objects.filter(store=second).exists()
    assert OAuthStateSession.objects.get(store=second).status == 'failed'
    new_revoke.assert_called_once_with('synthetic-new-uncommitted-credential', 'synthetic-new-uncommitted-token')
    previous_revoke.assert_not_called()
    assert complete(client, payload, route).status_code == 409
    assert new_revoke.call_count == 1


@pytest.mark.parametrize('route', ['manual', 'automatic'])
def test_other_configuration_cannot_replace_existing_authorization(lazada_context, monkeypatch, route):
    client, store, config = lazada_context
    assert complete(client, pending(lazada_context), route).status_code == 200
    existing = MarketplaceStoreAuthorization.objects.get(store=store)
    second_config = PlatformIntegrationConfig.objects.create(tenant=config.tenant, platform=config.platform,
        account_alias='second-config', environment=config.environment, status=config.status, regions=config.regions,
        contract_version=config.contract_version, callback_url=config.callback_url, scopes=[],
        platform_config=config.platform_config, created_by=config.created_by)
    payload = pending((client, store, second_config))
    new_revoke, previous_revoke = watch_exchanged_references(monkeypatch)
    result = complete(client, payload, route)
    assert result.status_code == 409, result.data
    existing.refresh_from_db()
    assert existing.integration_config_id == config.pk
    assert existing.credential_reference_version == 1
    assert MarketplaceStoreAuthorization.objects.count() == 1
    new_revoke.assert_called_once()
    previous_revoke.assert_not_called()


@pytest.mark.parametrize('route', ['manual', 'automatic'])
def test_same_store_and_config_reauthorization_still_rotates(lazada_context, route):
    client, store, _ = lazada_context
    assert complete(client, pending(lazada_context), route).status_code == 200
    payload = pending(lazada_context)
    assert complete(client, payload, route).status_code == 200
    existing = MarketplaceStoreAuthorization.objects.get(store=store)
    assert existing.credential_reference_version == 2
    assert existing.status == 'active'
    assert complete(client, payload, route).status_code == 409


def test_automatic_callback_rechecks_scope_changed_after_start(lazada_context, monkeypatch):
    client, store, config = lazada_context
    actor, scope = restricted_actor(store, config)
    client.force_authenticate(actor)
    payload = pending(lazada_context)
    scope.config = {'store_ids': [store.pk + 999], 'integration_config_ids': [config.pk]}
    scope.save()
    new_revoke, previous_revoke = watch_exchanged_references(monkeypatch)
    result = complete(client, payload, 'automatic')
    assert result.status_code == 409, result.data
    assert 'OAUTH_CALLBACK_REJECTED' in str(result.data)
    assert not MarketplaceStoreAuthorization.objects.exists()
    assert OAuthStateSession.objects.get().status == 'failed'
    new_revoke.assert_called_once()
    previous_revoke.assert_not_called()
