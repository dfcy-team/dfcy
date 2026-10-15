import pytest
from django.http import HttpResponse
from django.test import RequestFactory, override_settings

from apps.supply_chain.cutover import LegacySupplyWriteFence, LEGACY_PREFIXES


@pytest.mark.parametrize('prefix', LEGACY_PREFIXES)
@pytest.mark.parametrize('method', ['post', 'put', 'patch', 'delete'])
def test_legacy_business_mutations_are_blocked_without_calling_the_view(prefix, method):
    def unreachable(request):
        raise AssertionError('Legacy write handler must not run')
    with override_settings(SUPPLY_CHAIN_LEGACY_WRITES_ENABLED=False):
        response = LegacySupplyWriteFence(unreachable)(getattr(RequestFactory(), method)(prefix))
    assert response.status_code == 409 and b'LEGACY_SUPPLY_READ_ONLY' in response.content


@pytest.mark.parametrize('method', ['get', 'head', 'options'])
def test_legacy_reads_and_new_workflow_remain_accessible_to_their_existing_authorizers(method):
    middleware = LegacySupplyWriteFence(lambda request: HttpResponse(status=204))
    with override_settings(SUPPLY_CHAIN_LEGACY_WRITES_ENABLED=False):
        assert middleware(getattr(RequestFactory(), method)(LEGACY_PREFIXES[0])).status_code == 204
        for prefix in ['/api/internal/supply-chain/v2/', '/api/external/supplier/supply-chain/v2/',
                       '/api/internal/products/', '/api/internal/packing/', '/api/finance/']:
            assert middleware(RequestFactory().post(prefix)).status_code == 204
        assert middleware(RequestFactory().post('/api/external/supplier/consolidations/attachments/1/download-ticket/')).status_code == 204


def test_legacy_rollback_switch_is_explicit_and_only_affects_legacy_write_gate():
    middleware = LegacySupplyWriteFence(lambda request: HttpResponse(status=204))
    with override_settings(SUPPLY_CHAIN_LEGACY_WRITES_ENABLED=True):
        assert middleware(RequestFactory().post(LEGACY_PREFIXES[0])).status_code == 204
