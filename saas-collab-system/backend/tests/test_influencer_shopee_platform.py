import pytest
from apps.influencers.models import Influencer, InfluencerPlatformAccount
from tests.test_influencer_archive_associations import _records, _archive, _post, _url

pytestmark = pytest.mark.django_db


def test_create_related_shopee_archive_and_filter():
    r = _records('shopee-related')
    response = _post(r, _archive('shop-account', platform='shopee'))
    assert response.status_code == 201, response.data
    data = response.data['data']
    created = Influencer.objects.get(pk=data['id'])
    assert created.platform == 'shopee' and created.pk != r.source.pk
    assert InfluencerPlatformAccount.Platform.SHOPEE == 'shopee'
    assert any(item['platform'] == 'shopee' for item in data['platform_accounts'])
    assert r.client.get(_url(r.source.pk)).data['data']['results'][-1]['platform'] == 'shopee'
    result = r.client.get('/api/internal/influencers/', {'platform':'shopee', 'include_nickname_id':'true'})
    assert result.status_code == 200
    assert [item['id'] for item in result.data['data']['results']] == [created.pk]
    r.source.refresh_from_db(); assert r.source.platform == 'tiktok'


def test_create_standalone_shopee_archive_without_numeric_id():
    r = _records('shopee-standalone')
    payload = _archive('new-shop', platform='shopee')
    payload['profile']['external_influencer_id'] = ''
    response = r.client.post('/api/internal/influencers/?include_form=true', payload, format='json')
    assert response.status_code == 201, response.data
    data = response.data['data']
    assert data['platform'] == 'shopee' and data['nickname_id'] == 'new-shop.creator'
    assert data['profile']['external_influencer_id'] == ''
