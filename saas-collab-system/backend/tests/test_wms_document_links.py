import pytest
from apps.supply_chain.models import WmsDocumentLink
from tests.test_supply_chain_v2_foundation import world
from tests.test_supply_chain_v2_logistics import setup, write
from tests.test_supply_chain_v2_wms_reconciliation import grant_sales_view, wms_line, confirmed_receipt, BASE


@pytest.mark.django_db
def test_manual_document_link_preview_replay_and_deactivate(world):
    buyer, first, second, carrier, warehouse = setup(world)
    grant_sales_view(buyer)
    api, inbound = confirmed_receipt(world, buyer, [first], carrier, warehouse)
    fact = wms_line(buyer, warehouse, first.lines.get().sku, quantity=99)
    root = f'wms-inbound-documents/{fact.pk}/'
    candidates = api.get(BASE + root + 'link-candidates/')
    assert candidates.status_code == 200, candidates.data
    assert candidates.data['data']['items'][0]['id'] == inbound['id']
    preview = api.get(BASE + root + 'link-preview/', {'inbound_id': inbound['id']})
    assert preview.status_code == 200, preview.data
    data = preview.data['data']
    assert data['status'] == 'needs_review'
    body = {'inbound_id': inbound['id'], 'expected_version': data['version'],
            'preview_token': data['preview_token'], 'reason': '历史单据补录'}
    linked = write(api, root + 'links/', body, 'manual-link')
    assert linked.status_code == 200, linked.data
    assert write(api, root + 'links/', body, 'manual-link').status_code == 200
    assert WmsDocumentLink.objects.count() == 1
    row = linked.data['data']['inbounds'][0]
    assert row['association_status'] == 'needs_review'
    removed = write(api, root + f"links/{row['manual_link_id']}/deactivate/",
                    {'expected_version': row['manual_link_version'], 'reason': '误关联'}, 'manual-unlink')
    assert removed.status_code == 200, removed.data
    assert removed.data['data']['inbounds'] == []
    record = WmsDocumentLink.objects.get()
    assert not record.is_active and record.deactivated_by == buyer
