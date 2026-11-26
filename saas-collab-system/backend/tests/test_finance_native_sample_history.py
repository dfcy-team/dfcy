import pytest
from types import SimpleNamespace
from apps.finance.summary_cost_classification import collect_classifications
from apps.masterdata.models import StoreMaster
from apps.influencers.models import Influencer, SampleFulfillment
from tests.test_finance_summary import context

pytestmark = pytest.mark.django_db(transaction=True)


def test_native_sample_keyset_pages_are_sql_bounded_and_keep_legacy_tie_order(context):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from django.utils import timezone
    _,user,dataset,_=context
    store=StoreMaster.objects.get(pk=dataset.metadata['store_ids'][0])
    influencer=Influencer.objects.create(tenant=user.tenant,code='keyset-sample',name='Synthetic',platform='tiktok')
    samples=[SampleFulfillment(tenant=user.tenant,fulfillment_no=f'PAGE-{i}',request_key=f'page-{i}',
        request_hash='c'*64,influencer=influencer,store=store,owner=user,sample_order_no='\tpage-order\u3000') for i in range(501)]
    for sample in samples:
        sample.save()
    fixed_time=timezone.now()
    for sample in samples:
        sample.created_at=fixed_time
        sample.save(update_fields=["created_at"])
    order=SimpleNamespace(pk=900,store_id=store.pk,external_order_id='page-order',raw_status='completed',normalized_status='completed',delivered_at_utc=None)
    legacy=collect_classifications(user,{store.pk:store},[order],[],native=False)
    with CaptureQueriesContext(connection) as captured:
        native=collect_classifications(user,{store.pk:store},[order],[],native=True)
    assert native==legacy
    quoted_table=connection.ops.quote_name(SampleFulfillment._meta.db_table)
    queries=[q['sql'] for q in captured if ('FROM '+quoted_table) in q['sql']]
    assert len(queries)==3 and all('LIMIT 500' in q and 'OFFSET' not in q for q in queries)
    assert len(native[(store.pk,'page-order')]['evidence']['sample_ids'])==501


def test_native_sample_lookup_matches_legacy_python_strip_and_stays_store_scoped(context):
    _, user, dataset, _ = context
    store = StoreMaster.objects.get(pk=dataset.metadata['store_ids'][0])
    influencer = Influencer.objects.create(tenant=user.tenant, code='history-sample', name='Synthetic', platform='tiktok')
    identifiers = ['order-space', 'order-tab', 'order-unicode']
    padded = ['  order-space  ', '\torder-tab\t', '\u3000order-unicode\u3000']
    orders = [SimpleNamespace(pk=900+i, store_id=store.pk, external_order_id=value,
        raw_status='completed', normalized_status='completed', delivered_at_utc=None) for i, value in enumerate(identifiers)]
    for i, identifier in enumerate(padded):
        SampleFulfillment.objects.create(tenant=user.tenant, fulfillment_no=f'HIST-{i}', request_key=f'hist-{i}',
            request_hash='a'*64, influencer=influencer, store=store, owner=user,
            sample_order_no=identifier)
    other_store = StoreMaster.objects.create(tenant=user.tenant, platform=store.platform, code='history-other',
        name='Synthetic other', country_code=store.country_code, currency=store.currency)
    unrelated = SimpleNamespace(pk=999, store_id=other_store.pk, external_order_id='order-space',
        raw_status='completed', normalized_status='completed', delivered_at_utc=None)
    # Different store's same identifier is not visible to the selected source scope.
    SampleFulfillment.objects.create(tenant=user.tenant, fulfillment_no='HIST-OTHER', request_key='hist-other',
        request_hash='b'*64, influencer=influencer, store=other_store, owner=user, sample_order_no='order-space')
    stores = {store.pk: store}
    legacy = collect_classifications(user, stores, orders, [], native=False)
    native = collect_classifications(user, stores, orders, [], native=True)
    assert native == legacy
    assert all(native[(store.pk, key)]['category'] == 'sample' for key in identifiers)
    assert len(native) == 3
    assert unrelated.store_id not in stores
