from types import SimpleNamespace as O
import pytest
from apps.influencers.video_registered_reconcile import identity_matches


def pair():
    return (O(tenant_id=1,store_id=23,external_video_id='123',creator_username='@alice',influencer_id=None),
        O(tenant_id=1,store_id=23,external_content_id='123',platform='tiktok',influencer_id=2,
          influencer=O(tenant_id=1,platform='tiktok',handle='alice')))


def test_exact_registered_video_matches():
    assert identity_matches(*pair())


@pytest.mark.parametrize(('field','value'),[('tenant_id',2),('store_id',24),('external_video_id','456'),('creator_username','bob'),('creator_username',''),('influencer_id',99)])
def test_identity_conflicts_rejected(field,value):
    video,registered=pair();setattr(video,field,value)
    assert not identity_matches(video,registered)
