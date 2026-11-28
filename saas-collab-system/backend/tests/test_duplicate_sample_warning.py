import pytest
from django.db import connection
from apps.tenants.models import Tenant
from apps.influencers.models import SampleFulfillment
from apps.influencers.services import create_sample_fulfillment
from tests.test_influencer_fulfillment import user_with_permissions, base_records

pytestmark = pytest.mark.django_db
URL = "/api/internal/influencers/resolve/"

def setup_records():
    tenant = Tenant.objects.create(name="Warning", code="warning")
    user, client = user_with_permissions(tenant, "warning-user", "influencers.fulfillment.view", "influencers.fulfillment.manage")
    store, creator, task = base_records(tenant, user, "warning")
    rows=[]
    for index,status in enumerate(["pending","shipped","delivered","overdue","blacklisted","completed","cancelled","published","live_creator"]):
        row,_=create_sample_fulfillment(user=user,validated_data={"fulfillment_no":f"WARN-{index}","influencer":creator,"store":store,"owner":user,"outreach_task":task},item_payloads=[],request_key=f"warn-{index}")
        with connection.cursor() as cursor:
            cursor.execute(f"UPDATE {connection.ops.quote_name(SampleFulfillment._meta.db_table)} SET status=%s WHERE id=%s",[status,row.pk])
        rows.append(row)
    return tenant,user,client,creator,rows

def test_duplicate_warning_latest_three_exact_projection_and_all_states():
    tenant,user,client,creator,rows=setup_records()
    before=SampleFulfillment.objects.count()
    response=client.get(URL,{"duplicate_influencer":creator.pk})
    assert response.status_code==200,response.data
    records=response.data["data"]["records"]
    assert [r["status"] for r in records]==["blacklisted","overdue","delivered"]
    assert all(set(r)=={"fulfillment_no","status"} for r in records)
    with connection.cursor() as cursor:
        cursor.execute(f"UPDATE {connection.ops.quote_name(SampleFulfillment._meta.db_table)} SET is_deleted=1 WHERE id IN (%s,%s,%s)",[rows[i].pk for i in [2,3,4]])
    assert [r["status"] for r in client.get(URL,{"duplicate_influencer":creator.pk}).data["data"]["records"]]==["shipped","pending"]
    assert SampleFulfillment.objects.count()==before

@pytest.mark.parametrize("value",["", "0", "01", "-1", "1,2", "١", "9223372036854775808"])
def test_duplicate_warning_rejects_invalid_ids(value):
    tenant=Tenant.objects.create(name="Invalid",code="invalid")
    _,client=user_with_permissions(tenant,"invalid-reader","influencers.fulfillment.manage")
    assert client.get(URL,{"duplicate_influencer":value}).status_code==400

def test_duplicate_warning_cross_tenant_and_denied():
    tenant,user,client,creator,rows=setup_records()
    other=Tenant.objects.create(name="Other",code="other-warning")
    _,foreign=user_with_permissions(other,"foreign-warning","influencers.fulfillment.manage")
    assert foreign.get(URL,{"duplicate_influencer":creator.pk}).status_code==404
    _,denied=user_with_permissions(tenant,"denied-warning")
    assert denied.get(URL,{"duplicate_influencer":creator.pk}).status_code==403


from tests.test_influencer_country_scope import scoped
from apps.influencers.models import Influencer, SampleItem

def test_duplicate_warning_scopes_target_aliases_stores_and_item_warehouses(scoped):
    d=scoped
    creator=d['creators'][0]
    alias=d['creators'][4]
    hidden=d['creators'][2]
    with connection.cursor() as cursor:
        cursor.execute(f"UPDATE {connection.ops.quote_name(Influencer._meta.db_table)} SET handle=%s WHERE id IN (%s,%s,%s)",['shared.creator',creator.pk,alias.pk,hidden.pk])
    def add(number,who,store,warehouse=None):
        row=SampleFulfillment.objects.create(tenant=d['tenant'],fulfillment_no=number,request_key=number,request_hash='test',influencer=who,store=store,owner=d['user'])
        if warehouse:
            SampleItem.objects.create(tenant=d['tenant'],fulfillment=row,warehouse=warehouse,site_code='PH',requested_sku='SKU',quantity=1)
        return row
    add('visible-self',creator,d['store'])
    add('visible-alias',alias,d['store'])
    add('hidden-alias',hidden,d['store'])
    add('hidden-store',creator,d['outside_store'])
    add('hidden-item',creator,d['store'],d['outside_warehouse'])
    response=d['client'].get(URL,{'duplicate_influencer':creator.pk})
    assert response.status_code==200,response.data
    assert [r['fulfillment_no'] for r in response.data['data']['records']]==['visible-alias','visible-self']
    assert d['client'].get(URL,{'duplicate_influencer':hidden.pk}).status_code==404


def test_duplicate_warning_inactive_target_and_multiple_visible_stores():
    tenant,user,client,creator,rows=setup_records()
    from tests.test_influencer_fulfillment import store_for
    store=store_for(tenant,'second-visible')
    SampleFulfillment.objects.create(tenant=tenant,fulfillment_no='OTHER-STORE',request_key='other-store',request_hash='test',influencer=creator,store=store,owner=user,external_product_id='other-product')
    with connection.cursor() as cursor:
        cursor.execute(f"UPDATE {connection.ops.quote_name(Influencer._meta.db_table)} SET status='inactive' WHERE id=%s",[creator.pk])
    response=client.get(URL,{'duplicate_influencer':creator.pk})
    assert response.status_code==200,response.data
    assert [r['fulfillment_no'] for r in response.data['data']['records']]==['OTHER-STORE',rows[4].fulfillment_no,rows[3].fulfillment_no]
    from django.utils import timezone
    with connection.cursor() as cursor:
        cursor.execute(f"UPDATE {connection.ops.quote_name(Influencer._meta.db_table)} SET is_deleted=1,deleted_at=%s WHERE id=%s",[timezone.now(),creator.pk])
    assert client.get(URL,{'duplicate_influencer':creator.pk}).status_code==404
