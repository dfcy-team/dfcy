from django.test import override_settings
from apps.influencers.completion_provenance import completion_reason, parse_completion_reason

IDENTITY={'tenant_id':1,'sample_id':2,'actor_id':3}
def parse(reason,**override):return parse_completion_reason(reason,**{**IDENTITY,**override})
def make(external='video:with:delimiter'):
    return completion_reason(**IDENTITY,raw_id=9223372036854775807,external_id=external)

def test_completion_marker_exact_identity_and_tampering():
    reason=make()
    assert parse(reason)==(9223372036854775807,'video:with:delimiter',True)
    for key in IDENTITY:
        assert parse(reason,**{key:99})[-1] is False
    assert parse(reason[:-1]+('a' if reason[-1]!='a' else 'b'))[-1] is False
    assert parse('api_video_verified_v2:1:video:'+'0'*32)[-1] is False
    assert parse('api_video_verified:1:legacy')==(1,'legacy',False)
    assert parse('api_video_verified_v2:bad') is None

def test_maximum_external_id_fits_and_key_rotation_fails_closed():
    with override_settings(SECRET_KEY='test-old-purpose-key',SECRET_KEY_FALLBACKS=[]):reason=make('x'*160)
    assert len(reason)<=240
    with override_settings(SECRET_KEY='test-new-purpose-key',SECRET_KEY_FALLBACKS=['test-old-purpose-key']):assert parse(reason)[-1] is True
    with override_settings(SECRET_KEY='test-new-purpose-key',SECRET_KEY_FALLBACKS=[]):assert parse(reason)[-1] is False


import pytest
from django.utils import timezone
from apps.accounts.models import CustomUser
from apps.influencers.models import VideoResult
from apps.influencers.serializers import SampleFulfillmentSerializer
from apps.influencers.sample_completion_evidence import attach_completion_evidence
from tests.test_sample_video_completion import data, run

@pytest.mark.django_db
@pytest.mark.parametrize('external_id',['video-1','x'*160,'video:with:delimiters'])
def test_real_writer_issues_bound_marker_and_legacy_is_explicitly_unverified(data, external_id):
    data.video.external_video_id=external_id;data.video.save(update_fields=['external_video_id'])
    # The actual reconciler legitimately reuses an independently registered manual result.
    VideoResult.objects.create(tenant=data.tenant,influencer=data.creator,store=data.store,platform='tiktok',content_type='video',external_content_id=external_id,published_at=data.video.published_at,metric_date=timezone.localdate(),currency='PHP',source='manual')
    assert run(data)=='completed'
    data.sample.refresh_from_db()
    event=data.sample.status_events.get()
    assert event.reason.startswith('api_video_verified_v2:') and len(event.reason)<=240
    original=event.reason
    def evidence():
        attach_completion_evidence([data.sample]);return SampleFulfillmentSerializer(data.sample).data['completion_evidence']
    assert evidence()['kind']=='system'
    assert evidence()['video_id']==external_id
    event.reason=original[:-1]+('a' if original[-1]!='a' else 'b');event.save(update_fields=['reason'])
    assert evidence()['kind']=='linked'
    event.reason=original;event.actor=CustomUser.objects.create_user(username='different-evidence-actor',tenant=data.tenant);event.save(update_fields=['reason','actor'])
    assert evidence()['kind']=='linked'
    event.actor=data.actor;event.save(update_fields=['actor'])
    with override_settings(SECRET_KEY='test-rotated-purpose-key',SECRET_KEY_FALLBACKS=[]):assert evidence()['kind']=='linked'
    event.reason=f'api_video_verified:{data.video.pk}:{external_id}';event.save(update_fields=['reason'])
    assert evidence()['kind']=='linked'
